"""Render the dependency-free, offline vocabulary-atlas explorer."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from string import Template
from typing import Any, cast

from refspec.registry.infrastructure.semantic_foundation import (
    SemanticFoundationError,
    SemanticRing,
    validate_ring_relation,
)

from .queries import native_concept_relation_id

EXPLORER_TYPE = "urn:ref:type:VocabularyAtlasExplorerView"
EXPLORER_SCHEMA_VERSION = "4.0"

# The renderer and the executable acceptance gate consume this same table.
# Each row says which planning-row field one shipped control evaluates and how
# an unset control behaves.
PLANNING_FILTER_SEMANTICS: tuple[Mapping[str, str], ...] = (
    {
        "dimension": "ring",
        "rowField": "semanticRing",
        "statePath": "activeRings",
        "operator": "setContains",
    },
    {
        "dimension": "sourceModule",
        "rowField": "sourceModule",
        "statePath": "activeConceptFacets.sourceModules",
        "operator": "equalsWhenSet",
    },
    {
        "dimension": "resourceId",
        "rowField": "resourceId",
        "statePath": "activeConceptFacets.resourceIds",
        "operator": "equalsWhenSet",
    },
    {
        "dimension": "participation",
        "rowField": "atlasParticipation",
        "statePath": "activeConceptFacets.participations",
        "operator": "equalsWhenSet",
    },
    {
        "dimension": "disposition",
        "rowField": "disposition",
        "statePath": "activePlanningDisposition",
        "operator": "equalsWhenSet",
    },
)

# One canonical description drives the shipped concept, native-relation, and
# mapping-assertion controls plus the independent Python/Node acceptance gate.
# Endpoint fields mean that an edge is eligible only when both endpoint
# concepts also satisfy the active concept controls.
EXPLORER_FILTER_SEMANTICS: tuple[Mapping[str, object], ...] = (
    {
        "recordKind": "concept",
        "idField": "viewId",
        "filters": (
            {
                "dimension": "release",
                "rowField": "releaseId",
                "statePath": "activeReleases",
                "operator": "setContains",
            },
            {
                "dimension": "ring",
                "rowField": "semanticRing",
                "statePath": "activeRings",
                "operator": "setContains",
            },
            *(
                {
                    "dimension": field,
                    "rowField": field,
                    "statePath": f"activeConceptFacets.{field}",
                    "operator": "arrayContainsWhenSet",
                }
                for field in (
                    "sourceModules",
                    "resourceIds",
                    "participations",
                    "languages",
                    "lifecycle",
                    "sourceCollections",
                    "sourceUrls",
                    "cfrTitles",
                    "cfrParts",
                )
            ),
        ),
        "endpointFields": (),
    },
    {
        "recordKind": "nativeRelation",
        "idField": "id",
        "filters": (
            {
                "dimension": "nativePredicate",
                "rowField": "predicate",
                "statePath": "activeNativePredicates",
                "operator": "setContains",
            },
            {
                "dimension": "ring",
                "rowField": "semanticRing",
                "statePath": "activeRings",
                "operator": "setContains",
            },
        ),
        "endpointFields": ("subjectViewId", "objectViewId"),
    },
    {
        "recordKind": "mappingAssertion",
        "idField": "id",
        "filters": (
            {
                "dimension": "mappingVisibility",
                "statePath": "mappingsActive",
                "operator": "enabled",
            },
            {
                "dimension": "ring",
                "rowField": "semanticRing",
                "statePath": "activeRings",
                "operator": "setContains",
            },
            {
                "dimension": "mappingPredicate",
                "rowField": "relation",
                "statePath": "activeMappingPredicate",
                "operator": "equalsWhenSet",
            },
            {
                "dimension": "mappingLifecycleStatus",
                "rowField": "effectiveLifecycleStatus",
                "statePath": "activeMappingLifecycleStatus",
                "operator": "equalsWhenSet",
            },
            {
                "dimension": "evidenceClass",
                "rowField": "evidenceClasses",
                "statePath": "activeEvidenceClass",
                "operator": "arrayContainsWhenSet",
            },
        ),
        "endpointFields": ("sourceViewId", "targetViewId"),
    },
)

_MODEL_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "title",
        "atlas",
        "selectionPolicy",
        "summary",
        "releaseContext",
        "facets",
        "conceptReleases",
        "concepts",
        "nativeRelations",
        "mappingAssertions",
    }
)
_ATLAS_FIELDS = frozenset({"kind", "assetId", "manifestDigest", "distributionDigest", "counts", "quadCount"})
_PARENT_FIELDS = frozenset({"assetId", "manifestDigest", "distributionDigest"})
_COUNT_FIELDS = frozenset(
    {
        "conceptReleases",
        "concepts",
        "releaseRecords",
        "relationBundles",
        "evidenceAssertions",
        "mappingAssertions",
        "machineProofs",
    }
)
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
_RELEASE_FIELDS = frozenset({"releaseId", "label", "semanticRing", "conceptCount", "shownConceptCount"})
_CONCEPT_FIELDS = frozenset(
    {
        "viewId",
        "conceptId",
        "releaseId",
        "semanticRing",
        "recordId",
        "recordDigest",
        "label",
        "selectionReasons",
        "sourceModules",
        "resourceIds",
        "participations",
        "languages",
        "lifecycle",
        "sourceCollections",
        "sourceUrls",
        "cfrTitles",
        "cfrParts",
    }
)
_CONCEPT_TEXT_FIELDS = frozenset({"notation", "definition", "scopeNote"})
_CONCEPT_OPTIONAL_FIELDS = _CONCEPT_TEXT_FIELDS | {"searchLabels"}
_MAPPING_FIELDS = frozenset(
    {
        "id",
        "sourceViewId",
        "targetViewId",
        "sourceConcept",
        "targetConcept",
        "sourceRelease",
        "targetRelease",
        "semanticRing",
        "relation",
        "relationLabel",
        "lifecycleStatus",
        "effectiveLifecycleStatus",
        "supersedes",
        "supersededBy",
        "directEvidenceAssertions",
        "evidenceAssertions",
        "evidenceClasses",
        "externalEvidence",
        "candidateIds",
        "validationReceiptIds",
        "machineProofs",
    }
)
_NATIVE_RELATION_FIELDS = frozenset(
    {
        "id",
        "subjectViewId",
        "objectViewId",
        "subjectConcept",
        "objectConcept",
        "releaseId",
        "semanticRing",
        "predicate",
        "predicateLabel",
        "sourceRecordId",
        "sourceRecordDigest",
    }
)
_RING_ORDER = ("subject", "entity", "value", "legalIdentity")
_RINGS = frozenset(_RING_ORDER)
_SELECTION_REASONS = frozenset(
    {
        "mappingEndpoint",
        "nativeRelationEndpoint",
        "releaseRepresentative",
    }
)
_NATIVE_RELATION_LABELS = {
    "http://www.w3.org/2004/02/skos/core#broader": "broader",
    "http://www.w3.org/2004/02/skos/core#narrower": "narrower",
    "http://www.w3.org/2004/02/skos/core#related": "related",
    "https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUse": "thesaurus use",
    "https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUsedFor": "thesaurus used for",
}
_EVIDENCE_CLASSES = frozenset(
    {
        "machineQualified",
        "machineReviewed",
        "publisherAsserted",
        "operatorAdopted",
        "humanReviewed",
        "ruleGenerated",
    }
)
_RELEASE_CONTEXT_FIELDS = frozenset({"sourceApprovals", "planningRows"})
_RELEASE_CONTEXT_PIN_FIELDS = frozenset({"planningIndex", "publicationDecision"})
_PLANNING_INDEX_FIELDS = frozenset({"role", "id", "indexDigest", "fileDigest"})
_PUBLICATION_DECISION_FIELDS = frozenset({"id", "recordDigest", "schemaVersion"})
_SOURCE_APPROVAL_FIELDS = frozenset({"releaseId", "manifestDigest", "semanticRing", "disposition", "conditions"})
_PLANNING_ROW_FIELDS = frozenset(
    {
        "rowId",
        "rowDigest",
        "sourceModule",
        "resourceId",
        "facet",
        "semanticRing",
        "planningStatus",
        "intendedUses",
        "disposition",
        "reason",
    }
)
_PLANNING_ROW_OPTIONAL_FIELDS = frozenset({"atlasParticipation", "releaseId"})
_FACET_FIELDS = frozenset(
    {
        "sourceModules",
        "resourceIds",
        "participations",
        "languages",
        "lifecycle",
        "sourceCollections",
        "sourceUrls",
        "cfrTitles",
        "cfrParts",
        "nativePredicates",
        "mappingPredicates",
        "mappingLifecycleStatuses",
        "evidenceClasses",
        "planningDispositions",
    }
)
_CONCEPT_FACET_FIELDS = frozenset(
    {
        "sourceModules",
        "resourceIds",
        "participations",
        "languages",
        "lifecycle",
        "sourceCollections",
        "sourceUrls",
        "cfrTitles",
        "cfrParts",
    }
)


class AtlasExplorerError(ValueError):
    """The bounded explorer model is not the closed Atlas 2.0 shape."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AtlasExplorerError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AtlasExplorerError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    actual = set(value)
    if not expected <= actual or not actual <= expected | optional:
        raise AtlasExplorerError(f"{label} fields differ from Atlas explorer {EXPLORER_SCHEMA_VERSION}")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AtlasExplorerError(f"{label} must be non-empty trimmed text")
    return value


def _count(value: object, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise AtlasExplorerError(f"{label} must be a {qualifier} integer")
    return value


def _ring(value: object, label: str) -> str:
    if not isinstance(value, str) or value not in _RINGS:
        raise AtlasExplorerError(f"{label} must be an Atlas 2.0 semantic ring")
    return value


def _text_array(value: object, label: str) -> tuple[str, ...]:
    rows = _sequence(value, label)
    result = tuple(_text(item, f"{label}[]") for item in rows)
    if len(result) != len(set(result)):
        raise AtlasExplorerError(f"{label} must not repeat values")
    return result


def _canonical_text_array(value: object, label: str) -> tuple[str, ...]:
    result = _text_array(value, label)
    if list(result) != sorted(result):
        raise AtlasExplorerError(f"{label} must use canonical text order")
    return result


def _validate_release_context(value: object) -> Mapping[str, Any]:
    context = _mapping(value, "atlas explorer releaseContext")
    _exact_fields(
        context,
        _RELEASE_CONTEXT_FIELDS,
        "atlas explorer releaseContext",
        optional=_RELEASE_CONTEXT_PIN_FIELDS,
    )
    index_pin = context.get("planningIndex")
    decision_pin = context.get("publicationDecision")
    approvals = _sequence(
        context.get("sourceApprovals"),
        "atlas explorer releaseContext.sourceApprovals",
    )
    planning_rows = _sequence(
        context.get("planningRows"),
        "atlas explorer releaseContext.planningRows",
    )
    if "planningIndex" not in context or "publicationDecision" not in context:
        if "planningIndex" in context or "publicationDecision" in context or approvals or planning_rows:
            raise AtlasExplorerError("atlas explorer releaseContext must supply both exact pins or neither")
        return context

    index = _mapping(index_pin, "atlas explorer releaseContext.planningIndex")
    _exact_fields(
        index,
        _PLANNING_INDEX_FIELDS,
        "atlas explorer releaseContext.planningIndex",
    )
    if index.get("role") != "AtlasIndex":
        raise AtlasExplorerError("atlas explorer releaseContext planning index has the wrong role")
    for field in ("id", "indexDigest", "fileDigest"):
        _text(index.get(field), f"atlas explorer releaseContext.planningIndex.{field}")

    decision = _mapping(
        decision_pin,
        "atlas explorer releaseContext.publicationDecision",
    )
    _exact_fields(
        decision,
        _PUBLICATION_DECISION_FIELDS,
        "atlas explorer releaseContext.publicationDecision",
    )
    for field in _PUBLICATION_DECISION_FIELDS:
        _text(
            decision.get(field),
            f"atlas explorer releaseContext.publicationDecision.{field}",
        )

    approval_ids: set[str] = set()
    for position, raw in enumerate(approvals):
        label = f"atlas explorer releaseContext.sourceApprovals[{position}]"
        row = _mapping(raw, label)
        _exact_fields(row, _SOURCE_APPROVAL_FIELDS, label)
        release_id = _text(row.get("releaseId"), f"{label}.releaseId")
        if release_id in approval_ids:
            raise AtlasExplorerError("atlas explorer repeats a source approval")
        approval_ids.add(release_id)
        _text(row.get("manifestDigest"), f"{label}.manifestDigest")
        _ring(row.get("semanticRing"), f"{label}.semanticRing")
        if row.get("disposition") != "approved":
            raise AtlasExplorerError("atlas explorer source approval must be approved")
        conditions = _sequence(row.get("conditions"), f"{label}.conditions")
        for condition_position, condition_raw in enumerate(conditions):
            condition_label = f"{label}.conditions[{condition_position}]"
            condition = _mapping(condition_raw, condition_label)
            _exact_fields(
                condition,
                frozenset({"kind", "statement"}),
                condition_label,
            )
            _text(condition.get("kind"), f"{condition_label}.kind")
            _text(condition.get("statement"), f"{condition_label}.statement")

    row_ids: list[str] = []
    for position, raw in enumerate(planning_rows):
        label = f"atlas explorer releaseContext.planningRows[{position}]"
        row = _mapping(raw, label)
        _exact_fields(
            row,
            _PLANNING_ROW_FIELDS,
            label,
            optional=_PLANNING_ROW_OPTIONAL_FIELDS,
        )
        row_id = _text(row.get("rowId"), f"{label}.rowId")
        row_ids.append(row_id)
        for field in (
            "rowDigest",
            "sourceModule",
            "resourceId",
            "facet",
            "planningStatus",
            "disposition",
            "reason",
        ):
            _text(row.get(field), f"{label}.{field}")
        _ring(row.get("semanticRing"), f"{label}.semanticRing")
        if "atlasParticipation" in row:
            _text(row.get("atlasParticipation"), f"{label}.atlasParticipation")
        if "releaseId" in row:
            _text(row.get("releaseId"), f"{label}.releaseId")
        _canonical_text_array(row.get("intendedUses"), f"{label}.intendedUses")
    if len(row_ids) != len(set(row_ids)) or row_ids != sorted(row_ids):
        raise AtlasExplorerError("atlas explorer planning rows must be unique and in canonical order")
    return context


def _validate_facets(value: object) -> Mapping[str, tuple[str, ...]]:
    facets = _mapping(value, "atlas explorer facets")
    _exact_fields(facets, _FACET_FIELDS, "atlas explorer facets")
    return {
        field: _canonical_text_array(
            facets.get(field),
            f"atlas explorer facets.{field}",
        )
        for field in _FACET_FIELDS
    }


def _validate_model(model: Mapping[str, Any]) -> None:
    _exact_fields(model, _MODEL_FIELDS, "atlas explorer")
    if model.get("type") != EXPLORER_TYPE or model.get("schemaVersion") != EXPLORER_SCHEMA_VERSION:
        raise AtlasExplorerError("atlas explorer type or schemaVersion differs from " + EXPLORER_SCHEMA_VERSION)
    _text(model.get("title"), "atlas explorer title")
    release_context = _validate_release_context(model.get("releaseContext"))
    facets = _validate_facets(model.get("facets"))

    atlas = _mapping(model.get("atlas"), "atlas explorer atlas")
    kind = atlas.get("kind")
    expected_atlas_fields = _ATLAS_FIELDS if kind == "atlas" else _ATLAS_FIELDS | {"parent"}
    if kind not in {"atlas", "projection"}:
        raise AtlasExplorerError("atlas explorer kind must be atlas or projection")
    _exact_fields(atlas, expected_atlas_fields, "atlas explorer atlas")
    for field in ("assetId", "manifestDigest", "distributionDigest"):
        _text(atlas.get(field), f"atlas explorer atlas.{field}")
    _count(atlas.get("quadCount"), "atlas explorer atlas.quadCount", positive=True)
    counts = _mapping(atlas.get("counts"), "atlas explorer atlas.counts")
    _exact_fields(counts, _COUNT_FIELDS, "atlas explorer atlas.counts")
    for field in _COUNT_FIELDS:
        _count(counts.get(field), f"atlas explorer atlas.counts.{field}")
    if kind == "projection":
        parent = _mapping(atlas.get("parent"), "atlas explorer atlas.parent")
        _exact_fields(parent, _PARENT_FIELDS, "atlas explorer atlas.parent")
        for field in _PARENT_FIELDS:
            _text(parent.get(field), f"atlas explorer atlas.parent.{field}")

    selection = _mapping(model.get("selectionPolicy"), "atlas explorer selectionPolicy")
    _exact_fields(selection, _SELECTION_FIELDS, "atlas explorer selectionPolicy")
    if selection.get("type") != "boundedExplorerView" or selection.get("version") != EXPLORER_SCHEMA_VERSION:
        raise AtlasExplorerError("atlas explorer selectionPolicy differs from " + EXPLORER_SCHEMA_VERSION)
    _text(selection.get("id"), "atlas explorer selectionPolicy.id")
    max_concepts = _count(
        selection.get("maxConcepts"),
        "atlas explorer selectionPolicy.maxConcepts",
        positive=True,
    )
    max_mappings = _count(
        selection.get("maxMappingAssertions"),
        "atlas explorer selectionPolicy.maxMappingAssertions",
    )

    summary = _mapping(model.get("summary"), "atlas explorer summary")
    _exact_fields(summary, _SUMMARY_FIELDS, "atlas explorer summary")
    shown_concepts = _count(summary.get("shownConceptCount"), "atlas explorer summary.shownConceptCount")
    shown_mappings = _count(
        summary.get("shownMappingAssertionCount"),
        "atlas explorer summary.shownMappingAssertionCount",
    )
    shown_native_relations = _count(
        summary.get("shownNativeRelationCount"),
        "atlas explorer summary.shownNativeRelationCount",
    )
    available_concepts = _count(
        summary.get("availableConceptCount"),
        "atlas explorer summary.availableConceptCount",
    )
    available_mappings = _count(
        summary.get("availableMappingAssertionCount"),
        "atlas explorer summary.availableMappingAssertionCount",
    )
    available_native_relations = _count(
        summary.get("availableNativeRelationCount"),
        "atlas explorer summary.availableNativeRelationCount",
    )
    if not isinstance(summary.get("truncated"), bool):
        raise AtlasExplorerError("atlas explorer summary.truncated must be boolean")

    releases = _sequence(model.get("conceptReleases"), "atlas explorer conceptReleases")
    release_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(releases):
        label = f"atlas explorer conceptReleases[{index}]"
        row = _mapping(raw, label)
        _exact_fields(row, _RELEASE_FIELDS, label)
        release_id = _text(row.get("releaseId"), f"{label}.releaseId")
        if release_id in release_by_id:
            raise AtlasExplorerError("atlas explorer repeats a concept release")
        _text(row.get("label"), f"{label}.label")
        _ring(row.get("semanticRing"), f"{label}.semanticRing")
        concept_count = _count(row.get("conceptCount"), f"{label}.conceptCount", positive=True)
        shown_count = _count(row.get("shownConceptCount"), f"{label}.shownConceptCount")
        if shown_count > concept_count:
            raise AtlasExplorerError("atlas explorer release shows more concepts than it contains")
        release_by_id[release_id] = row
    if len(release_by_id) != counts["conceptReleases"]:
        raise AtlasExplorerError("atlas explorer concept release count differs from the distribution")

    concepts = _sequence(model.get("concepts"), "atlas explorer concepts")
    concept_by_view_id: dict[str, Mapping[str, Any]] = {}
    release_concept_keys: set[tuple[str, str]] = set()
    shown_by_release: dict[str, int] = {release_id: 0 for release_id in release_by_id}
    for index, raw in enumerate(concepts):
        label = f"atlas explorer concepts[{index}]"
        row = _mapping(raw, label)
        _exact_fields(row, _CONCEPT_FIELDS, label, optional=_CONCEPT_OPTIONAL_FIELDS)
        view_id = _text(row.get("viewId"), f"{label}.viewId")
        concept_id = _text(row.get("conceptId"), f"{label}.conceptId")
        release_id = _text(row.get("releaseId"), f"{label}.releaseId")
        ring = _ring(row.get("semanticRing"), f"{label}.semanticRing")
        if view_id in concept_by_view_id or (release_id, concept_id) in release_concept_keys:
            raise AtlasExplorerError("atlas explorer repeats a release-scoped concept")
        release = release_by_id.get(release_id)
        if release is None or release["semanticRing"] != ring:
            raise AtlasExplorerError("atlas explorer concept differs from its concept release")
        _text(row.get("recordId"), f"{label}.recordId")
        _text(row.get("recordDigest"), f"{label}.recordDigest")
        _text(row.get("label"), f"{label}.label")
        reasons = _text_array(row.get("selectionReasons"), f"{label}.selectionReasons")
        if not set(reasons) <= _SELECTION_REASONS:
            raise AtlasExplorerError("atlas explorer concept has an unsupported selection reason")
        for field in _CONCEPT_TEXT_FIELDS & set(row):
            _text(row[field], f"{label}.{field}")
        if "searchLabels" in row:
            search_labels = _text_array(row["searchLabels"], f"{label}.searchLabels")
            if list(search_labels) != sorted(
                search_labels,
                key=lambda value: (value.casefold(), value),
            ):
                raise AtlasExplorerError(f"{label}.searchLabels must use canonical label order")
        for field in _CONCEPT_FACET_FIELDS:
            _canonical_text_array(row.get(field), f"{label}.{field}")
        concept_by_view_id[view_id] = row
        release_concept_keys.add((release_id, concept_id))
        shown_by_release[release_id] += 1
    if any(release_by_id[key]["shownConceptCount"] != value for key, value in shown_by_release.items()):
        raise AtlasExplorerError("atlas explorer release shown counts differ from its concepts")

    native_relations = _sequence(
        model.get("nativeRelations"),
        "atlas explorer nativeRelations",
    )
    native_relation_ids: set[str] = set()
    for index, raw in enumerate(native_relations):
        label = f"atlas explorer nativeRelations[{index}]"
        row = _mapping(raw, label)
        _exact_fields(row, _NATIVE_RELATION_FIELDS, label)
        relation_id = _text(row.get("id"), f"{label}.id")
        if relation_id in native_relation_ids:
            raise AtlasExplorerError("atlas explorer repeats a native relation")
        subject = concept_by_view_id.get(_text(row.get("subjectViewId"), f"{label}.subjectViewId"))
        object_concept = concept_by_view_id.get(_text(row.get("objectViewId"), f"{label}.objectViewId"))
        if subject is None or object_concept is None:
            raise AtlasExplorerError("atlas explorer native relation has an unavailable endpoint")
        release_id = _text(row.get("releaseId"), f"{label}.releaseId")
        ring = _ring(row.get("semanticRing"), f"{label}.semanticRing")
        if (
            subject["releaseId"] != release_id
            or object_concept["releaseId"] != release_id
            or subject["semanticRing"] != ring
            or object_concept["semanticRing"] != ring
            or subject["conceptId"] != row.get("subjectConcept")
            or object_concept["conceptId"] != row.get("objectConcept")
        ):
            raise AtlasExplorerError("atlas explorer native relation differs from its exact release endpoints")
        predicate = _text(row.get("predicate"), f"{label}.predicate")
        expected_label = _NATIVE_RELATION_LABELS.get(predicate)
        if expected_label is None or row.get("predicateLabel") != expected_label:
            raise AtlasExplorerError("atlas explorer native relation predicate is unsupported")
        source_record_id = _text(
            row.get("sourceRecordId"),
            f"{label}.sourceRecordId",
        )
        source_record_digest = _text(
            row.get("sourceRecordDigest"),
            f"{label}.sourceRecordDigest",
        )
        if source_record_id != subject["recordId"] or source_record_digest != subject["recordDigest"]:
            raise AtlasExplorerError("atlas explorer native relation does not bind its source concept record")
        expected_id = native_concept_relation_id(
            subject_concept=cast(str, row["subjectConcept"]),
            predicate_iri=predicate,
            object_concept=cast(str, row["objectConcept"]),
            release_id=release_id,
            source_record_id=source_record_id,
            source_record_digest=source_record_digest,
        )
        if relation_id != expected_id:
            raise AtlasExplorerError("atlas explorer native relation id differs from its facts")
        native_relation_ids.add(relation_id)

    mappings = _sequence(model.get("mappingAssertions"), "atlas explorer mappingAssertions")
    mapping_ids: set[str] = set()
    for index, raw in enumerate(mappings):
        label = f"atlas explorer mappingAssertions[{index}]"
        row = _mapping(raw, label)
        _exact_fields(row, _MAPPING_FIELDS, label, optional=frozenset({"context"}))
        mapping_id = _text(row.get("id"), f"{label}.id")
        if mapping_id in mapping_ids:
            raise AtlasExplorerError("atlas explorer repeats a mapping assertion")
        source = concept_by_view_id.get(_text(row.get("sourceViewId"), f"{label}.sourceViewId"))
        target = concept_by_view_id.get(_text(row.get("targetViewId"), f"{label}.targetViewId"))
        if source is None or target is None or source is target:
            raise AtlasExplorerError("atlas explorer mapping assertion has an unavailable endpoint")
        ring = _ring(row.get("semanticRing"), f"{label}.semanticRing")
        endpoint_facts = (
            (source, "sourceConcept", "sourceRelease"),
            (target, "targetConcept", "targetRelease"),
        )
        if any(
            endpoint["semanticRing"] != ring
            or endpoint["conceptId"] != row[concept_field]
            or endpoint["releaseId"] != row[release_field]
            for endpoint, concept_field, release_field in endpoint_facts
        ):
            raise AtlasExplorerError("atlas explorer mapping assertion differs from its endpoints")
        relation = _text(row.get("relation"), f"{label}.relation")
        _text(row.get("relationLabel"), f"{label}.relationLabel")
        if row.get("lifecycleStatus") != "current":
            raise AtlasExplorerError(
                "atlas explorer mapping assertion lifecycleStatus must be current"
            )
        supersedes = _canonical_text_array(
            row.get("supersedes"),
            f"{label}.supersedes",
        )
        superseded_by = _canonical_text_array(
            row.get("supersededBy"),
            f"{label}.supersededBy",
        )
        effective_status = row.get("effectiveLifecycleStatus")
        if effective_status not in {"current", "superseded"} or (
            effective_status == "superseded"
        ) != bool(superseded_by):
            raise AtlasExplorerError(
                "atlas explorer mapping assertion effective lifecycle differs from supersession links"
            )
        if mapping_id in supersedes or mapping_id in superseded_by:
            raise AtlasExplorerError("atlas explorer mapping assertion cannot supersede itself")
        direct = _text_array(row.get("directEvidenceAssertions"), f"{label}.directEvidenceAssertions")
        evidence = _text_array(row.get("evidenceAssertions"), f"{label}.evidenceAssertions")
        if not direct or not set(direct) <= set(evidence):
            raise AtlasExplorerError("atlas explorer mapping assertion evidence closure is incomplete")
        classes = _text_array(row.get("evidenceClasses"), f"{label}.evidenceClasses")
        if not classes or not set(classes) <= _EVIDENCE_CLASSES:
            raise AtlasExplorerError("atlas explorer mapping assertion evidence class is unsupported")
        for field in ("externalEvidence", "candidateIds", "validationReceiptIds", "machineProofs"):
            _text_array(row.get(field), f"{label}.{field}")
        context_value = row.get("context")
        if "context" in row and not isinstance(context_value, Mapping):
            raise AtlasExplorerError(f"{label}.context must be an object")
        try:
            validate_ring_relation(
                cast(SemanticRing, ring),
                relation,
                cast(Mapping[str, str], context_value) if isinstance(context_value, Mapping) else None,
            )
        except SemanticFoundationError as error:
            raise AtlasExplorerError(f"{label} violates ring relation semantics: {error}") from error
        mapping_ids.add(mapping_id)

    if (
        shown_concepts != len(concepts)
        or shown_native_relations != len(native_relations)
        or shown_mappings != len(mappings)
        or shown_concepts > available_concepts
        or shown_native_relations > available_native_relations
        or shown_mappings > available_mappings
        or shown_concepts > max_concepts
        or shown_mappings > max_mappings
        or available_mappings != counts["mappingAssertions"]
    ):
        raise AtlasExplorerError("atlas explorer summary or selection bounds differ from its records")

    approval_release_ids = {
        cast(str, row["releaseId"])
        for row in cast(
            Sequence[Mapping[str, Any]],
            release_context["sourceApprovals"],
        )
    }
    if approval_release_ids and not set(release_by_id) <= approval_release_ids:
        raise AtlasExplorerError("atlas explorer concept releases are absent from source approvals")
    expected_facets = {
        field: tuple(
            sorted(
                {
                    cast(str, item)
                    for concept in concepts
                    for item in cast(Sequence[str], _mapping(concept, "concept")[field])
                }
            )
        )
        for field in _CONCEPT_FACET_FIELDS
    }
    planning_rows = cast(
        Sequence[Mapping[str, Any]],
        release_context["planningRows"],
    )
    expected_facets["sourceModules"] = tuple(
        sorted(
            set(expected_facets["sourceModules"])
            | {cast(str, _mapping(row, "planning row")["sourceModule"]) for row in planning_rows}
        )
    )
    expected_facets["resourceIds"] = tuple(
        sorted(
            set(expected_facets["resourceIds"])
            | {cast(str, _mapping(row, "planning row")["resourceId"]) for row in planning_rows}
        )
    )
    expected_facets["participations"] = tuple(
        sorted(
            set(expected_facets["participations"])
            | {
                cast(str, _mapping(row, "planning row")["atlasParticipation"])
                for row in planning_rows
                if "atlasParticipation" in _mapping(row, "planning row")
            }
        )
    )
    expected_facets.update(
        {
            "nativePredicates": tuple(
                sorted({cast(str, _mapping(row, "native relation")["predicate"]) for row in native_relations})
            ),
            "mappingPredicates": tuple(
                sorted({cast(str, _mapping(row, "mapping assertion")["relation"]) for row in mappings})
            ),
            "mappingLifecycleStatuses": tuple(
                sorted(
                    {
                        cast(
                            str,
                            _mapping(row, "mapping assertion")[
                                "effectiveLifecycleStatus"
                            ],
                        )
                        for row in mappings
                    }
                )
            ),
            "evidenceClasses": tuple(
                sorted(
                    {
                        evidence_class
                        for raw in mappings
                        for evidence_class in cast(
                            Sequence[str],
                            _mapping(raw, "mapping assertion")["evidenceClasses"],
                        )
                    }
                )
            ),
            "planningDispositions": tuple(
                sorted({cast(str, _mapping(row, "planning row")["disposition"]) for row in planning_rows})
            ),
        }
    )
    if facets != expected_facets:
        raise AtlasExplorerError("atlas explorer facet catalog differs from its exact records")
    expected_truncated = (
        shown_concepts < available_concepts
        or shown_native_relations < available_native_relations
        or shown_mappings < available_mappings
    )
    if summary["truncated"] is not expected_truncated:
        raise AtlasExplorerError("atlas explorer summary.truncated differs from its records")


class _Template(Template):
    delimiter = "@@"


_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>@@title · RefSpec atlas explorer</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%230c1211'/%3E%3Cpath d='M18 32h28M32 18v28' stroke='%2374c7b8' stroke-width='4'/%3E%3Ccircle cx='18' cy='32' r='7' fill='%23e9b95f'/%3E%3Ccircle cx='46' cy='32' r='7' fill='%2374c7b8'/%3E%3Ccircle cx='32' cy='18' r='6' fill='%238eafd5'/%3E%3C/svg%3E">
  <style>
    :root {
      --ink: #edf1ed;
      --muted: #9ba8a2;
      --faint: #68756f;
      --paper: #0c1211;
      --paper-raised: #111a18;
      --rule: #26332f;
      --rule-strong: #3b4c46;
      --accent: #e9b95f;
      --accent-soft: rgba(233, 185, 95, .12);
      --danger: #ee8b78;
      --focus: #8cd3c7;
      --serif: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 68% 32%, rgba(70, 111, 101, .12), transparent 34rem),
        var(--paper);
      font: 14px/1.45 var(--sans);
      overflow: hidden;
    }
    button, input, select { font: inherit; }
    button, a { -webkit-tap-highlight-color: transparent; }
    button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible, canvas:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .skip-link {
      position: fixed;
      top: .5rem;
      left: .5rem;
      z-index: 20;
      padding: .55rem .8rem;
      color: #07100e;
      background: var(--focus);
      transform: translateY(-160%);
    }
    .skip-link:focus { transform: translateY(0); }

    .shell {
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100%;
      min-height: 0;
    }
    .appbar {
      display: grid;
      grid-template-columns: minmax(15rem, 1fr) auto auto;
      gap: 1.5rem;
      align-items: center;
      min-height: 74px;
      padding: .9rem 1.1rem .85rem 1.35rem;
      border-bottom: 1px solid var(--rule);
      background: rgba(12, 18, 17, .93);
      backdrop-filter: blur(12px);
    }
    .identity { min-width: 0; }
    .eyebrow {
      display: block;
      color: var(--accent);
      font: 600 10px/1.2 var(--mono);
      letter-spacing: .14em;
      text-transform: uppercase;
    }
    h1 {
      margin: .18rem 0 0;
      overflow: hidden;
      font: 500 clamp(1.15rem, 2vw, 1.55rem)/1.15 var(--serif);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .seal {
      display: flex;
      gap: .55rem;
      align-items: center;
      color: var(--muted);
      white-space: nowrap;
    }
    .seal-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #80c99a;
      box-shadow: 0 0 0 4px rgba(128, 201, 154, .1);
    }
    .seal strong { color: var(--ink); font-size: .82rem; font-weight: 600; }
    .seal code { color: var(--faint); font: 11px/1.2 var(--mono); }
    .metrics { display: flex; gap: 1.35rem; }
    .metric { min-width: 4.3rem; text-align: right; }
    .metric b { display: block; font: 600 1rem/1 var(--mono); }
    .metric span { color: var(--faint); font-size: .7rem; letter-spacing: .04em; text-transform: uppercase; }

    .workspace {
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr) 282px;
      min-height: 0;
    }
    .panel {
      min-height: 0;
      overflow: auto;
      scrollbar-color: var(--rule-strong) transparent;
    }
    .controls {
      padding: 1rem 1rem 1.5rem 1.2rem;
      border-right: 1px solid var(--rule);
      background: rgba(14, 21, 20, .78);
    }
    .inspector {
      padding: 1rem 1.1rem 1.5rem;
      border-left: 1px solid var(--rule);
      background: rgba(14, 21, 20, .82);
    }
    .panel h2, .panel h3 {
      margin: 0;
      font-size: .72rem;
      font-weight: 650;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    .panel h2 { color: var(--ink); }
    .panel h3 { color: var(--faint); }
    .control-section {
      padding: 1rem 0;
      border-bottom: 1px solid var(--rule);
    }
    .control-section:last-child { border-bottom: 0; }
    .search-wrap { position: relative; margin-top: .7rem; }
    #search {
      width: 100%;
      min-height: 42px;
      padding: .65rem 2rem .65rem .72rem;
      color: var(--ink);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: #0a100f;
    }
    #search::placeholder { color: #63716c; }
    #search::-webkit-search-cancel-button { display: none; }
    .key {
      position: absolute;
      top: 50%;
      right: .6rem;
      color: var(--faint);
      font: 11px/1 var(--mono);
      transform: translateY(-50%);
    }
    .results { display: grid; gap: 1px; margin-top: .45rem; }
    .result {
      width: 100%;
      padding: .48rem .1rem;
      color: var(--ink);
      border: 0;
      border-bottom: 1px solid rgba(38, 51, 47, .7);
      background: transparent;
      text-align: left;
      cursor: pointer;
    }
    .result:hover, .result.active { color: var(--accent); background: var(--accent-soft); }
    .result span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .result small { display: block; color: var(--faint); font-size: .7rem; }
    .result .match { color: var(--muted); }
    .result-summary { display: block; padding: .42rem .1rem; color: var(--faint); font-size: .7rem; }
    .search-ring-control { margin-top: .62rem; }
    .filter-list { display: grid; gap: .58rem; margin-top: .75rem; }
    .filter {
      display: grid;
      grid-template-columns: 14px 1fr auto;
      gap: .55rem;
      align-items: center;
      min-height: 26px;
      color: var(--muted);
      cursor: pointer;
    }
    .release-filter { grid-template-columns: 14px 9px minmax(0, 1fr) auto; }
    .relation-filter { grid-template-columns: 14px 20px minmax(0, 1fr); }
    .filter input { width: 14px; height: 14px; margin: 0; accent-color: var(--accent); }
    .filter .swatch { width: 9px; height: 9px; border-radius: 50%; background: var(--swatch); }
    .filter .label { overflow: hidden; color: var(--ink); text-overflow: ellipsis; white-space: nowrap; }
    .filter small { color: var(--faint); font: 10px/1 var(--mono); }
    .filter-copy { display: grid; min-width: 0; gap: .22rem; }
    .filter-copy small { display: block; }
    .edge-key {
      width: 20px;
      height: 0;
      border-top: 2px solid var(--edge-color);
    }
    .edge-key.mapping { border-top-style: dashed; }
    .hint { margin: .7rem 0 0; color: var(--faint); font-size: .75rem; }
    .facet-selects { display: grid; gap: .62rem; margin-top: .75rem; }
    .facet-control { display: grid; gap: .25rem; color: var(--faint); font-size: .7rem; }
    .facet-control select {
      width: 100%;
      min-height: 34px;
      padding: .42rem 1.9rem .42rem .5rem;
      overflow: hidden;
      color: var(--ink);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: #0a100f;
      text-overflow: ellipsis;
    }
    .scope-summary { margin: .68rem 0 0; color: var(--muted); font-size: .75rem; }
    .planning-rows { display: grid; gap: .38rem; margin-top: .7rem; }
    .planning-row {
      padding: .48rem 0;
      border-top: 1px solid rgba(38, 51, 47, .72);
      color: var(--muted);
      font-size: .72rem;
    }
    .planning-row b, .planning-row small { display: block; overflow-wrap: anywhere; }
    .planning-row b { color: var(--ink); font-weight: 550; }
    .planning-row small { margin-top: .16rem; color: var(--faint); }
    .planning-row-count { display: block; margin-top: .55rem; color: var(--faint); font: 10px/1.4 var(--mono); }
    .render-limit { margin-top: .75rem; }
    .render-limit-heading {
      display: flex;
      gap: .75rem;
      align-items: center;
      justify-content: space-between;
      color: var(--ink);
      font-size: .78rem;
    }
    #render-limit-number {
      width: 4.8rem;
      min-height: 32px;
      padding: .35rem .42rem;
      color: var(--ink);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: #0a100f;
      font: 11px/1 var(--mono);
      text-align: right;
    }
    #render-limit-range {
      display: block;
      width: 100%;
      margin: .65rem 0 .25rem;
      accent-color: var(--accent);
      cursor: pointer;
    }
    .render-limit-scale {
      display: flex;
      justify-content: space-between;
      color: var(--faint);
      font: 10px/1 var(--mono);
    }
    .secondary-action {
      margin-top: .75rem;
      padding: .42rem .6rem;
      color: var(--muted);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: transparent;
      cursor: pointer;
    }
    .secondary-action:hover { color: var(--ink); border-color: var(--accent); }

    .stage { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
    #graph {
      display: block;
      width: 100%;
      height: 100%;
      opacity: 0;
      cursor: grab;
      transition: opacity .45s ease;
      touch-action: none;
    }
    #graph.ready { opacity: 1; }
    #graph.panning { cursor: grabbing; }
    .graph-tools {
      position: absolute;
      top: .75rem;
      right: .75rem;
      display: flex;
      overflow: hidden;
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: rgba(12, 18, 17, .92);
    }
    .graph-tools button {
      width: 38px;
      height: 38px;
      padding: 0;
      color: var(--muted);
      border: 0;
      border-right: 1px solid var(--rule);
      background: transparent;
      cursor: pointer;
    }
    .graph-tools button:last-child { border-right: 0; }
    .graph-tools button:hover { color: var(--accent); background: var(--accent-soft); }
    .mobile-only { display: none; }
    .legend-note {
      position: absolute;
      bottom: .8rem;
      left: .9rem;
      max-width: min(34rem, calc(100% - 1.8rem));
      margin: 0;
      color: var(--faint);
      font: 10px/1.45 var(--mono);
      pointer-events: none;
    }
    .graph-status {
      position: absolute;
      top: .85rem;
      left: .9rem;
      max-width: calc(100% - 12rem);
      padding: .38rem .52rem;
      color: var(--muted);
      border: 1px solid var(--rule);
      border-radius: 3px;
      background: rgba(12, 18, 17, .88);
      font: 10px/1.35 var(--mono);
      pointer-events: none;
    }
    .tooltip {
      position: absolute;
      z-index: 4;
      max-width: 260px;
      padding: .45rem .6rem;
      color: var(--ink);
      border: 1px solid var(--rule-strong);
      background: rgba(8, 13, 12, .96);
      box-shadow: 0 8px 26px rgba(0, 0, 0, .3);
      font-size: .78rem;
      pointer-events: none;
      transform: translate(12px, 12px);
    }
    .tooltip[hidden] { display: none; }
    .tooltip small { display: block; color: var(--faint); }

    .empty-state { margin-top: 1.4rem; color: var(--muted); }
    .empty-state strong { display: block; margin-bottom: .35rem; color: var(--ink); font: 500 1.15rem/1.25 var(--serif); }
    .inspector-content[hidden], .empty-state[hidden] { display: none; }
    .node-kicker { margin: 1.1rem 0 .25rem; color: var(--accent); font: 10px/1.2 var(--mono); text-transform: uppercase; }
    .node-title { margin: 0; font: 500 1.3rem/1.2 var(--serif); overflow-wrap: anywhere; }
    .node-release { display: flex; gap: .45rem; align-items: center; margin: .55rem 0 1rem; color: var(--muted); }
    .node-release i { width: 8px; height: 8px; border-radius: 50%; background: var(--node-color); }
    .facts { display: grid; grid-template-columns: 5.2rem 1fr; gap: .45rem .65rem; margin: 0; }
    .facts dt { color: var(--faint); font-size: .72rem; }
    .facts dd { margin: 0; color: var(--muted); overflow-wrap: anywhere; }
    .iri {
      display: block;
      max-height: 5.5rem;
      overflow: auto;
      color: var(--muted);
      font: 10px/1.45 var(--mono);
      text-decoration: none;
    }
    a.iri:hover { color: var(--accent); }
    .copy-button {
      margin-top: .65rem;
      padding: .4rem .55rem;
      color: var(--muted);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: transparent;
      cursor: pointer;
    }
    .copy-button:hover { color: var(--ink); border-color: var(--accent); }
    .connections { display: grid; gap: .35rem; margin-top: .7rem; }
    .connection {
      width: 100%;
      padding: .5rem .55rem;
      color: var(--muted);
      border: 0;
      border-left: 2px solid var(--connection-color);
      background: rgba(255, 255, 255, .02);
      text-align: left;
      cursor: pointer;
    }
    .connection:hover { color: var(--ink); background: rgba(255, 255, 255, .045); }
    .connection b { display: block; color: inherit; font-size: .78rem; font-weight: 550; }
    .connection small { display: block; color: var(--faint); }
    .connection-group { display: grid; gap: .3rem; }
    .mapping-endpoint { margin-top: .16rem; overflow-wrap: anywhere; }
    .mapping-endpoint strong { color: var(--muted); font-weight: 550; }
    .connection-evidence {
      margin: 0 0 .18rem .55rem;
      padding-left: .5rem;
      border-left: 1px solid var(--rule);
      color: var(--faint);
      font-size: .7rem;
    }
    .connection-evidence summary { color: var(--muted); cursor: pointer; }
    .reference-group { margin-top: .48rem; }
    .reference-group b { display: block; color: var(--muted); font-weight: 550; }
    .reference-group code, .reference-group a {
      display: block;
      margin-top: .16rem;
      overflow-wrap: anywhere;
      color: var(--faint);
      font: 10px/1.4 var(--mono);
      text-decoration: none;
    }
    .reference-group a:hover, .evidence-resolver:hover { color: var(--accent); }
    .evidence-resolver { display: inline-block; margin-top: .58rem; color: var(--muted); text-decoration: none; }

    .provenance {
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr) auto;
      align-items: center;
      min-height: 45px;
      border-top: 1px solid var(--rule);
      color: var(--faint);
      background: #0a100f;
      font-size: .72rem;
    }
    .provenance > * { padding: .65rem 1.1rem; }
    .provenance summary { color: var(--muted); cursor: pointer; }
    .provenance details[open] {
      position: absolute;
      right: 1rem;
      bottom: 3rem;
      left: 1rem;
      z-index: 8;
      padding: 1rem;
      border: 1px solid var(--rule-strong);
      background: #0a100f;
      box-shadow: 0 14px 50px rgba(0, 0, 0, .4);
    }
    .pin-grid { display: grid; grid-template-columns: 9rem 1fr; gap: .4rem .8rem; margin-top: .8rem; }
    .pin-grid code { overflow-wrap: anywhere; color: var(--muted); font: 10px/1.4 var(--mono); }
    .downloads { display: flex; gap: .9rem; justify-content: flex-end; white-space: nowrap; }
    .downloads a { color: var(--muted); text-decoration: none; }
    .downloads a:hover { color: var(--accent); }

    @media (max-width: 940px) {
      .workspace { grid-template-columns: 220px minmax(0, 1fr); }
      .inspector {
        position: absolute;
        top: 74px;
        right: 0;
        bottom: 45px;
        z-index: 6;
        width: min(310px, 86vw);
        box-shadow: -12px 0 40px rgba(0, 0, 0, .32);
        transform: translateX(100%);
        transition: transform .2s ease;
      }
      .inspector.open { transform: translateX(0); }
      .metrics .metric:nth-child(-n+2) { display: none; }
      .provenance { grid-template-columns: 220px minmax(0, 1fr); }
      .downloads { display: none; }
    }
    @media (max-width: 660px) {
      body { overflow: auto; }
      .shell { min-height: 100%; height: auto; grid-template-rows: auto minmax(36rem, 1fr) auto; }
      .appbar { grid-template-columns: minmax(0, 1fr) auto; gap: .8rem; }
      .seal code, .metrics { display: none; }
      .workspace { position: relative; grid-template-columns: 1fr; min-height: 36rem; }
      .controls {
        position: absolute;
        top: .6rem;
        left: .6rem;
        z-index: 5;
        width: min(230px, calc(100vw - 1.2rem));
        max-height: calc(100% - 1.2rem);
        border: 1px solid var(--rule-strong);
        box-shadow: 0 12px 36px rgba(0, 0, 0, .32);
        transform: translateX(calc(-100% - 1rem));
        transition: transform .2s ease;
      }
      .controls.open { transform: translateX(0); }
      .provenance { grid-template-columns: 1fr; }
      .provenance > :first-child { display: none; }
      .graph-tools { top: .6rem; right: .6rem; }
      .mobile-only { display: block; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#graph">Skip to graph</a>
  <div class="shell">
    <header class="appbar">
      <div class="identity">
        <span class="eyebrow">RefSpec vocabulary atlas</span>
        <h1>@@title</h1>
      </div>
      <div class="seal" aria-label="Atlas verified before publication">
        <span class="seal-dot" aria-hidden="true"></span>
        <span><strong>Sealed input</strong><br><code id="short-id"></code></span>
      </div>
      <div class="metrics" aria-label="Atlas totals">
        <div class="metric"><b id="metric-releases">—</b><span>releases</span></div>
        <div class="metric"><b id="metric-quads">—</b><span>quads</span></div>
        <div class="metric"><b id="metric-native">—</b><span>native relations</span></div>
      </div>
    </header>

    <main class="workspace">
      <aside class="panel controls" id="controls" aria-label="Graph controls">
        <h2>Explore the atlas</h2>
        <section class="control-section">
          <h3>Find a concept</h3>
          <div class="search-wrap">
            <input id="search" type="search" autocomplete="off" placeholder="Label, alias, notation, or identifier" aria-label="Find a concept" aria-controls="search-results" aria-expanded="false" aria-autocomplete="list" role="combobox">
            <span class="key" aria-hidden="true">/</span>
          </div>
          <label class="facet-control search-ring-control" for="search-ring">
            <span>Search within one semantic ring</span>
            <select id="search-ring" aria-label="Search within one semantic ring" required></select>
          </label>
          <p class="hint">One active ring keeps subject, entity, value, and legal-identity concepts in separate rankings.</p>
          <div class="results" id="search-results" role="listbox" aria-live="polite"></div>
        </section>
        <section class="control-section">
          <h3>Concept releases</h3>
          <div class="filter-list" id="release-filters"></div>
        </section>
        <section class="control-section">
          <h3>Semantic rings</h3>
          <div class="filter-list" id="ring-filters"></div>
          <p class="hint">Ring filters apply to concepts and every relationship attached to them.</p>
        </section>
        <section class="control-section" id="concept-facet-section">
          <h3>Source and concept facts</h3>
          <div class="facet-selects" id="concept-facet-filters"></div>
          <p class="hint">Each available fact comes from the exact release records or planning index. Empty facets stay out of the way.</p>
        </section>
        <section class="control-section">
          <h3>Source-native relations</h3>
          <div class="filter-list" id="native-filters"></div>
          <p class="hint">Solid lines preserve relations stated inside an exact source release. Paired inverse assertions share one drawn line but remain separate facts.</p>
        </section>
        <section class="control-section">
          <h3>Cross-release mappings</h3>
          <div class="filter-list" id="mapping-filters"></div>
          <div class="facet-selects" id="mapping-facet-filters"></div>
          <p class="hint">Dashed lines are typed cross-release mapping assertions. Arrowheads show every asserted source-to-target direction.</p>
        </section>
        <section class="control-section" id="release-context-section" hidden>
          <h3>Release controls</h3>
          <p class="scope-summary" id="release-context-summary"></p>
          <div class="planning-rows" id="source-approvals"></div>
          <div class="facet-selects" id="planning-facet-filters"></div>
          <div class="planning-rows" id="planning-rows"></div>
          <small class="planning-row-count" id="planning-row-count"></small>
        </section>
        <section class="control-section">
          <h3>Graph view</h3>
          <div class="render-limit">
            <label class="render-limit-heading" for="render-limit-number">
              <span>Maximum rendered concepts</span>
              <input id="render-limit-number" type="number" min="1" step="1" inputmode="numeric" aria-describedby="selection-note">
            </label>
            <input id="render-limit-range" type="range" min="1" step="1" aria-label="Maximum rendered concepts" aria-describedby="selection-note">
            <div class="render-limit-scale" aria-hidden="true"><span>1</span><span id="render-limit-max">—</span></div>
          </div>
          <p class="hint" id="selection-note"></p>
          <button class="secondary-action" type="button" id="reset-filters">Reset search and filters</button>
        </section>
      </aside>

      <section class="stage" id="stage" aria-label="Vocabulary graph">
        <canvas id="graph" tabindex="0" aria-describedby="graph-description"></canvas>
        <div class="graph-status" id="graph-status" aria-live="polite"></div>
        <p id="graph-description" class="legend-note">Search or select a concept to highlight its relationships; unrelated lines dim to graphite without hiding the current graph. Drag to pan. Scroll or use the controls to zoom. Solid lines are source-native relations; dashed lines are typed mappings, with arrows for every directional assertion.</p>
        <div class="graph-tools" aria-label="Graph view controls">
          <button class="mobile-only" type="button" id="toggle-controls" aria-label="Show filters">☰</button>
          <button type="button" id="zoom-in" aria-label="Zoom in">＋</button>
          <button type="button" id="zoom-out" aria-label="Zoom out">−</button>
          <button type="button" id="fit-view" aria-label="Fit graph to view">⌂</button>
        </div>
        <div class="tooltip" id="tooltip" hidden></div>
      </section>

      <aside class="panel inspector" id="inspector" aria-label="Concept inspector">
        <h2>Concept inspector</h2>
        <div class="empty-state" id="empty-inspector">
          <strong>Select a concept</strong>
          Search by label, or choose a point in the graph to inspect its source identity and exact relationships.
        </div>
        <div class="inspector-content" id="inspector-content" hidden>
          <p class="node-kicker" id="node-role"></p>
          <h3 class="node-title" id="node-title"></h3>
          <p class="node-release"><i id="node-swatch"></i><span id="node-release"></span></p>
          <dl class="facts">
            <dt>Source concept identity</dt>
            <dd><a class="iri" id="node-iri"></a><button class="copy-button" type="button" id="copy-iri">Copy IRI</button></dd>
            <dt id="notation-term" hidden>Notation</dt><dd id="notation-value" hidden></dd>
            <dt>Filtered native assertions</dt><dd id="node-native-count"></dd>
            <dt>Filtered mapping assertions</dt><dd id="node-mapping-count"></dd>
            <dt>Hierarchy parents</dt><dd id="node-parent-count"></dd>
            <dt>Hierarchy children</dt><dd id="node-child-count"></dd>
            <dt>Ancestors</dt><dd id="node-ancestor-count"></dd>
            <dt>Descendants</dt><dd id="node-descendant-count"></dd>
            <dt>Related concepts</dt><dd id="node-related-count"></dd>
          </dl>
          <section class="control-section" id="node-notes" hidden>
            <h3>Source notes</h3>
            <p class="hint" id="node-definition" hidden></p>
            <p class="hint" id="node-scope-note" hidden></p>
          </section>
          <section class="control-section">
            <h3>Relationships matching filters</h3>
            <div class="connections" id="connections"></div>
          </section>
          <section class="control-section" id="node-hierarchy" hidden>
            <h3>Hierarchy paths</h3>
            <p class="hint">Paths combine source-native hierarchy with directed broad and narrow cross-release mappings. Every route is composed of direct, source-asserted steps; an inferred multi-hop route remains distinct from a direct assertion.</p>
            <div class="connections" id="hierarchy-connections"></div>
          </section>
        </div>
      </aside>
    </main>

    <footer class="provenance">
      <div><span id="view-count"></span></div>
      <details>
        <summary>Provenance and exact pins</summary>
        <div class="pin-grid">
          <span>Atlas ID</span><code id="pin-id"></code>
          <span>Manifest</span><code id="pin-manifest"></code>
          <span>N-Quads</span><code id="pin-output"></code>
          <span>Selection</span><code id="pin-selection"></code>
          <span id="pin-index-label" hidden>Planning index</span><code id="pin-index" hidden></code>
          <span id="pin-decision-label" hidden>Decision</span><code id="pin-decision" hidden></code>
        </div>
      </details>
      <nav class="downloads" aria-label="Atlas downloads">
        <a href="atlas-manifest.json" download>Manifest</a>
        <a href="atlas.nq.gz" download>N-Quads · gzip</a>
        <a href="atlas-explorer.json" download>Explorer data</a>
        <a href="publication-decision.json" download>Decision</a>
        <a href="atlas-index.json" download id="index-download" hidden>Planning index</a>
        <a href="publication-manifest.json" download>Publication record</a>
      </nav>
    </footer>
  </div>

  <noscript>This explorer needs JavaScript to search and draw the focused graph. The complete atlas files and publication record remain downloadable.</noscript>
  <script id="atlas-data" type="application/json">@@atlas_data</script>
  <script>
  (() => {
    "use strict";

    const data = JSON.parse(document.getElementById("atlas-data").textContent);
    const canvas = document.getElementById("graph");
    const stage = document.getElementById("stage");
    const ctx = canvas.getContext("2d", { alpha: true });
    const tooltip = document.getElementById("tooltip");
    const search = document.getElementById("search");
    const searchRing = document.getElementById("search-ring");
    const resultBox = document.getElementById("search-results");
    const releaseFilters = document.getElementById("release-filters");
    const nativeFilters = document.getElementById("native-filters");
    const ringFilters = document.getElementById("ring-filters");
    const mappingFilters = document.getElementById("mapping-filters");
    const conceptFacetFilters = document.getElementById("concept-facet-filters");
    const mappingFacetFilters = document.getElementById("mapping-facet-filters");
    const planningFacetFilters = document.getElementById("planning-facet-filters");
    const planningRows = document.getElementById("planning-rows");
    const graphStatus = document.getElementById("graph-status");
    const renderLimitRange = document.getElementById("render-limit-range");
    const renderLimitNumber = document.getElementById("render-limit-number");
    const renderCapacity = Math.max(1, data.summary.shownConceptCount);
    const defaultRenderLimit = Math.min(180, renderCapacity);
    const maxSearchResults = 18;
    let renderLimitFrame = null;
    const palette = ["#74c7b8", "#efb65d", "#e77d6d", "#8eafd5", "#b3c76d", "#c497cf", "#67b6d4"];
    const subduedEdgeColor = "#24302c";
    const ringOrder = ["subject", "entity", "value", "legalIdentity"];
    const ringColors = { subject: "#e9b95f", entity: "#74c7b8", value: "#8eafd5", legalIdentity: "#c497cf" };
    const ringLabels = { subject: "Subject", entity: "Entity", value: "Value", legalIdentity: "Legal identity" };
    const symmetricMappingRelations = new Set([
      "http://www.w3.org/2004/02/skos/core#exactMatch",
      "http://www.w3.org/2004/02/skos/core#closeMatch",
      "http://www.w3.org/2004/02/skos/core#relatedMatch",
      "urn:ref:relation:entity:sameIdentityAs",
      "urn:ref:relation:entity:relatedEntity",
      "urn:ref:relation:value:exactCrosswalk"
    ]);
    const broaderMappingRelations = new Set([
      "http://www.w3.org/2004/02/skos/core#broadMatch",
      "urn:ref:relation:value:broadCrosswalk"
    ]);
    const narrowerMappingRelations = new Set([
      "http://www.w3.org/2004/02/skos/core#narrowMatch",
      "urn:ref:relation:value:narrowCrosswalk"
    ]);
    const directionalMappingRelations = new Set([
      ...broaderMappingRelations,
      ...narrowerMappingRelations,
      "urn:ref:relation:entity:successorOf",
      "urn:ref:relation:value:replacedBy",
      "urn:ref:relation:legal-identity:cites",
      "urn:ref:relation:legal-identity:amends",
      "urn:ref:relation:legal-identity:authorizes",
      "urn:ref:relation:legal-identity:implements"
    ]);
    const nativePredicateOrder = [
      "http://www.w3.org/2004/02/skos/core#broader",
      "http://www.w3.org/2004/02/skos/core#narrower",
      "http://www.w3.org/2004/02/skos/core#related",
      "https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUse",
      "https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUsedFor"
    ];
    const conceptFacetDefinitions = [
      ["sourceModules", "Source module"],
      ["resourceIds", "Resource"],
      ["participations", "Participation"],
      ["languages", "Language"],
      ["lifecycle", "Lifecycle event"],
      ["sourceCollections", "Source collection"],
      ["sourceUrls", "Source URL"],
      ["cfrTitles", "CFR title"],
      ["cfrParts", "CFR part"]
    ];
    /* explorer-filter-core:start */
    const explorerFilterSemantics = @@explorer_filter_semantics;

    function explorerStateValue(filterState, path) {
      return path.split(".").reduce((value, field) => value?.[field], filterState);
    }

    function explorerSetHas(selected, value) {
      if (selected instanceof Set) return selected.has(value);
      if (Array.isArray(selected)) return selected.includes(value);
      return false;
    }

    function explorerFilterMatches(record, specification, filterState) {
      const selected = explorerStateValue(filterState, specification.statePath);
      if (specification.operator === "enabled") return Boolean(selected);
      if (specification.operator === "setContains") {
        return explorerSetHas(selected, record[specification.rowField]);
      }
      if (specification.operator === "equalsWhenSet") {
        return !selected || record[specification.rowField] === selected;
      }
      if (specification.operator === "arrayContainsWhenSet") {
        return !selected || record[specification.rowField].includes(selected);
      }
      throw new Error(`Unsupported explorer filter operator: ${specification.operator}`);
    }

    function explorerConceptFromIndex(conceptIndex, viewId) {
      return conceptIndex instanceof Map ? conceptIndex.get(viewId) : conceptIndex[viewId];
    }

    function explorerRecordEligibleForState(recordKind, record, filterState, conceptIndex) {
      const semantics = explorerFilterSemantics.find(row => row.recordKind === recordKind);
      if (!semantics) throw new Error(`Unsupported explorer record kind: ${recordKind}`);
      if (!semantics.filters.every(filter => explorerFilterMatches(record, filter, filterState))) {
        return false;
      }
      return semantics.endpointFields.every(field => {
        const endpoint = explorerConceptFromIndex(conceptIndex, record[field]);
        return Boolean(endpoint)
          && explorerRecordEligibleForState("concept", endpoint, filterState, conceptIndex);
      });
    }

    function conceptEligibleForState(concept, filterState, conceptIndex) {
      return explorerRecordEligibleForState("concept", concept, filterState, conceptIndex);
    }

    function nativeRelationEligibleForState(relation, filterState, conceptIndex) {
      return explorerRecordEligibleForState("nativeRelation", relation, filterState, conceptIndex);
    }

    function mappingAssertionEligibleForState(mapping, filterState, conceptIndex) {
      return explorerRecordEligibleForState("mappingAssertion", mapping, filterState, conceptIndex);
    }
    /* explorer-filter-core:end */
    /* planning-filter-core:start */
    const planningFilterSemantics = @@planning_filter_semantics;

    function planningStateValue(filterState, path) {
      return path.split(".").reduce((value, field) => value?.[field], filterState);
    }

    function planningRowEligibleForState(row, filterState) {
      return planningFilterSemantics.every(specification => {
        const selected = planningStateValue(filterState, specification.statePath);
        if (specification.operator === "setContains") {
          return selected instanceof Set && selected.has(row[specification.rowField]);
        }
        if (specification.operator === "equalsWhenSet") {
          return !selected || row[specification.rowField] === selected;
        }
        throw new Error(`Unsupported planning filter operator: ${specification.operator}`);
      });
    }
    /* planning-filter-core:end */
    const releaseById = new Map(data.conceptReleases.map((release, index) => [release.releaseId, { ...release, index, color: palette[index % palette.length] }]));
    const conceptByViewId = new Map(data.concepts.map(concept => [concept.viewId, { ...concept, x: 0, y: 0 }]));
    const availableSearchRings = ringOrder.filter(ring => data.concepts.some(concept => concept.semanticRing === ring));
    const defaultSearchRing = "@@default_search_ring";
    const adjacency = new Map(data.concepts.map(concept => [concept.viewId, []]));
    data.mappingAssertions.forEach(mapping => {
      adjacency.get(mapping.sourceViewId).push({ kind: "mapping", edge: mapping, other: mapping.targetViewId, endpointRole: "source" });
      adjacency.get(mapping.targetViewId).push({ kind: "mapping", edge: mapping, other: mapping.sourceViewId, endpointRole: "target" });
    });
    data.nativeRelations.forEach(relation => {
      adjacency.get(relation.subjectViewId).push({ kind: "native", edge: relation, other: relation.objectViewId, direction: "outgoing" });
      adjacency.get(relation.objectViewId).push({ kind: "native", edge: relation, other: relation.subjectViewId, direction: "incoming" });
    });
    adjacency.forEach(links => links.sort((left, right) => {
      const leftRelation = left.edge.predicateLabel || left.edge.relationLabel;
      const rightRelation = right.edge.predicateLabel || right.edge.relationLabel;
      const leftConcept = conceptByViewId.get(left.other);
      const rightConcept = conceptByViewId.get(right.other);
      return left.kind.localeCompare(right.kind)
        || leftRelation.localeCompare(rightRelation)
        || leftConcept.label.localeCompare(rightConcept.label)
        || left.other.localeCompare(right.other);
    }));
    const nativeDisplayGroups = new Map();
    const nativePredicateFamilies = new Map([
      ["http://www.w3.org/2004/02/skos/core#broader", "hierarchy"],
      ["http://www.w3.org/2004/02/skos/core#narrower", "hierarchy"],
      ["http://www.w3.org/2004/02/skos/core#related", "related"],
      ["https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUse", "thesaurus-use"],
      ["https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUsedFor", "thesaurus-use"]
    ]);
    data.nativeRelations.forEach(relation => {
      const endpoints = [relation.subjectViewId, relation.objectViewId].sort();
      const family = nativePredicateFamilies.get(relation.predicate) || relation.predicate;
      const key = `${relation.releaseId}\u001f${family}\u001f${endpoints[0]}\u001f${endpoints[1]}`;
      if (!nativeDisplayGroups.has(key)) nativeDisplayGroups.set(key, []);
      nativeDisplayGroups.get(key).push(relation);
    });
    const hierarchyParents = new Map(data.concepts.map(concept => [concept.viewId, []]));
    const hierarchyChildren = new Map(data.concepts.map(concept => [concept.viewId, []]));
    data.nativeRelations.forEach(relation => {
      let child;
      let parent;
      if (relation.predicateLabel === "broader") {
        child = relation.subjectViewId;
        parent = relation.objectViewId;
      } else if (relation.predicateLabel === "narrower") {
        child = relation.objectViewId;
        parent = relation.subjectViewId;
      } else {
        return;
      }
      hierarchyParents.get(child).push({ kind: "native", other: parent, edge: relation });
      hierarchyChildren.get(parent).push({ kind: "native", other: child, edge: relation });
    });
    data.mappingAssertions.forEach(mapping => {
      if (broaderMappingRelations.has(mapping.relation)) {
        hierarchyParents.get(mapping.sourceViewId).push({ kind: "mapping", other: mapping.targetViewId, edge: mapping });
        hierarchyChildren.get(mapping.targetViewId).push({ kind: "mapping", other: mapping.sourceViewId, edge: mapping });
      } else if (narrowerMappingRelations.has(mapping.relation)) {
        hierarchyChildren.get(mapping.sourceViewId).push({ kind: "mapping", other: mapping.targetViewId, edge: mapping });
        hierarchyParents.get(mapping.targetViewId).push({ kind: "mapping", other: mapping.sourceViewId, edge: mapping });
      }
    });

    /* explorer-search-document-core:start */
    function normalizeSearch(value) {
      return String(value || "")
        .normalize("NFKD")
        .replace(/\p{M}+/gu, "")
        .toLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, " ")
        .trim()
        .replace(/\s+/g, " ");
    }
    function identifierTail(value) {
      const parts = String(value).split(/[\/#:]/).filter(Boolean);
      return parts.length ? parts[parts.length - 1] : String(value);
    }
    function buildSearchDocuments(concepts, facetDefinitions) {
      return concepts.map(concept => {
        const labels = [...new Set([concept.label, ...(concept.searchLabels || [])])];
        const normalizedLabels = labels.map(value => {
          const normalized = normalizeSearch(value);
          return { value, normalized, tokens: normalized.split(" ").filter(Boolean) };
        });
        const notation = normalizeSearch(concept.notation || "");
        const identifier = normalizeSearch(concept.conceptId);
        const identifierTailValue = normalizeSearch(identifierTail(concept.conceptId));
        const notes = normalizeSearch([concept.definition || "", concept.scopeNote || ""].join(" "));
        const sourceFacts = normalizeSearch(facetDefinitions.flatMap(([field]) => concept[field]).join(" "));
        return {
          concept,
          labels: normalizedLabels,
          displayLabel: normalizeSearch(concept.label),
          notation,
          identifier,
          identifierTail: identifierTailValue,
          notes,
          sourceFacts
        };
      });
    }
    /* explorer-search-document-core:end */
    function mappingRelationKind(mapping) {
      if (broaderMappingRelations.has(mapping.relation) || narrowerMappingRelations.has(mapping.relation)) return "directedHierarchy";
      if (directionalMappingRelations.has(mapping.relation)) return "directed";
      if (symmetricMappingRelations.has(mapping.relation)) return "symmetric";
      return "typed";
    }
    function mappingConnector(mapping) {
      const kind = mappingRelationKind(mapping);
      if (kind === "directedHierarchy" || kind === "directed") return `—${mapping.relationLabel}→`;
      if (kind === "symmetric") return `↔ ${mapping.relationLabel} ↔`;
      return `— ${mapping.relationLabel} —`;
    }
    const searchDocuments = buildSearchDocuments(data.concepts, conceptFacetDefinitions);

    const state = {
      activeReleases: new Set(data.conceptReleases.map(release => release.releaseId)),
      activeNativePredicates: new Set(nativePredicateOrder),
      activeRings: new Set(ringOrder),
      activeSearchRing: defaultSearchRing,
      activeConceptFacets: Object.fromEntries(conceptFacetDefinitions.map(([field]) => [field, ""])),
      activeMappingPredicate: "",
      activeMappingLifecycleStatus: "",
      activeEvidenceClass: "",
      activePlanningDisposition: "",
      mappingsActive: true,
      selected: null,
      hover: null,
      matches: new Set(),
      searchResults: [],
      activeSearchIndex: -1,
      renderedConceptIds: new Set(),
      renderedNativeGroups: [],
      renderedMappings: [],
      renderLimit: defaultRenderLimit,
      query: "",
      view: { x: 0, y: 0, k: 1 },
      width: 1,
      height: 1,
      dpr: 1,
      panning: false,
      dragStart: null
    };

    function formatNumber(value) { return new Intl.NumberFormat("en-US").format(value); }
    function formatQuantity(value, singular, plural = `${singular}s`) {
      return `${formatNumber(value)} ${value === 1 ? singular : plural}`;
    }
    function shortId(value) {
      const tail = value.split(":").pop();
      return tail.length > 16 ? `${tail.slice(0, 8)}…${tail.slice(-6)}` : tail;
    }
    function screenToWorld(x, y) {
      return { x: (x - state.view.x) / state.view.k, y: (y - state.view.y) / state.view.k };
    }
    function isConceptEligible(concept) {
      return conceptEligibleForState(concept, state, conceptByViewId);
    }
    function isConceptVisible(concept) {
      return isConceptEligible(concept) && state.renderedConceptIds.has(concept.viewId);
    }
    function isMappingEligible(mapping) {
      return mappingAssertionEligibleForState(mapping, state, conceptByViewId);
    }
    function isMappingVisible(mapping) {
      return isMappingEligible(mapping)
        && state.renderedConceptIds.has(mapping.sourceViewId)
        && state.renderedConceptIds.has(mapping.targetViewId);
    }
    function isNativeRelationEligible(relation) {
      return nativeRelationEligibleForState(relation, state, conceptByViewId);
    }
    function isNativeRelationVisible(relation) {
      return isNativeRelationEligible(relation)
        && state.renderedConceptIds.has(relation.subjectViewId)
        && state.renderedConceptIds.has(relation.objectViewId);
    }
    function hierarchyStepEligible(item) {
      return item.kind === "mapping" ? isMappingEligible(item.edge) : isNativeRelationEligible(item.edge);
    }
    function hierarchyNeighbors(viewId, index) {
      const result = new Map();
      index.get(viewId).forEach(item => {
        const other = conceptByViewId.get(item.other);
        if (hierarchyStepEligible(item) && isConceptEligible(other) && !result.has(item.other)) {
          result.set(item.other, { concept: other, step: { ...item, from: viewId, to: item.other } });
        }
      });
      return [...result.values()].sort((left, right) =>
        left.concept.label.localeCompare(right.concept.label)
        || left.concept.viewId.localeCompare(right.concept.viewId)
      );
    }
    function hierarchyClosure(viewId, index) {
      const distances = new Map();
      const pending = hierarchyNeighbors(viewId, index).map(item => ({
        concept: item.concept,
        depth: 1,
        path: [item.step]
      }));
      let pendingIndex = 0;
      while (pendingIndex < pending.length) {
        const current = pending[pendingIndex];
        pendingIndex += 1;
        const previous = distances.get(current.concept.viewId);
        if (current.concept.viewId === viewId || (previous && previous.depth <= current.depth)) continue;
        distances.set(current.concept.viewId, current);
        hierarchyNeighbors(current.concept.viewId, index).forEach(item => {
          pending.push({
            concept: item.concept,
            depth: current.depth + 1,
            path: [...current.path, item.step]
          });
        });
      }
      return [...distances.values()].sort((left, right) => left.depth - right.depth
        || left.concept.label.localeCompare(right.concept.label)
        || left.concept.viewId.localeCompare(right.concept.viewId));
    }
    function hierarchyPathKinds(path) {
      const kinds = new Set(path.map(step => step.kind === "mapping" ? "cross-release mapping" : "source-native hierarchy"));
      return [...kinds].join(" + ");
    }
    function isLinkEligible(link) {
      return link.kind === "mapping" ? isMappingEligible(link.edge) : isNativeRelationEligible(link.edge);
    }
    function conceptRadius(concept) {
      if (concept.selectionReasons.includes("mappingEndpoint")) return 5.2;
      if (concept.selectionReasons.includes("nativeRelationEndpoint")) return 4.4;
      return 3.4;
    }

    function computeRenderedConcepts() {
      const rendered = new Set();
      const eligible = data.concepts
        .map(concept => conceptByViewId.get(concept.viewId))
        .filter(isConceptEligible);
      const eligibleLinkCache = new Map();
      const linksFor = viewId => {
        if (!eligibleLinkCache.has(viewId)) {
          eligibleLinkCache.set(viewId, adjacency.get(viewId).filter(isLinkEligible));
        }
        return eligibleLinkCache.get(viewId);
      };
      const add = viewId => {
        if (rendered.size < state.renderLimit && conceptByViewId.has(viewId)) rendered.add(viewId);
      };
      const selected = state.selected ? conceptByViewId.get(state.selected) : null;
      if (selected && isConceptEligible(selected)) add(selected.viewId);

      const degreeOrder = eligible.slice().sort((left, right) => {
        const degreeDifference = linksFor(right.viewId).length - linksFor(left.viewId).length;
        return degreeDifference
          || left.label.localeCompare(right.label)
          || left.viewId.localeCompare(right.viewId);
      });
      const searchSeeds = state.query
        ? state.searchResults.slice(0, 12).map(result => result.document.concept)
        : [];
      const seeds = searchSeeds.length ? searchSeeds : degreeOrder.slice(0, 18);
      seeds.forEach(concept => add(concept.viewId));
      seeds.forEach(concept => linksFor(concept.viewId).forEach(link => add(link.other)));
      degreeOrder.forEach(concept => add(concept.viewId));
      return rendered;
    }

    function refreshRenderedEdges() {
      state.renderedNativeGroups = [...nativeDisplayGroups.values()]
        .map(relations => relations.filter(isNativeRelationVisible))
        .filter(relations => relations.length);
      state.renderedMappings = data.mappingAssertions.filter(isMappingVisible);
    }

    function layout() {
      const visibleRows = data.concepts.filter(concept => state.renderedConceptIds.has(concept.viewId));
      const visibleReleases = data.conceptReleases.filter(release =>
        visibleRows.some(concept => concept.releaseId === release.releaseId)
      );
      const worldWidth = Math.max(920, visibleReleases.length * 310);
      const worldHeight = 720;
      visibleReleases.forEach((release, releaseIndex) => {
        const members = visibleRows
          .filter(concept => concept.releaseId === release.releaseId)
          .sort((a, b) => a.label.localeCompare(b.label) || a.viewId.localeCompare(b.viewId));
        const angle = visibleReleases.length === 1 ? 0 : (Math.PI * 2 * releaseIndex / visibleReleases.length) - Math.PI / 2;
        const cx = visibleReleases.length <= 2
          ? worldWidth * ((releaseIndex + 1) / (visibleReleases.length + 1))
          : worldWidth / 2 + Math.cos(angle) * worldWidth * .31;
        const cy = visibleReleases.length <= 2 ? worldHeight / 2 : worldHeight / 2 + Math.sin(angle) * worldHeight * .29;
        members.forEach((value, index) => {
          const concept = conceptByViewId.get(value.viewId);
          const theta = index * 2.399963229728653;
          const radius = 13.5 * Math.sqrt(index);
          concept.x = cx + Math.cos(theta) * radius;
          concept.y = cy + Math.sin(theta) * radius;
        });
      });
    }

    function bounds() {
      const visible = [...state.renderedConceptIds]
        .map(viewId => conceptByViewId.get(viewId))
        .filter(isConceptVisible);
      if (!visible.length) return { minX: 0, maxX: 1, minY: 0, maxY: 1 };
      return {
        minX: Math.min(...visible.map(node => node.x)),
        maxX: Math.max(...visible.map(node => node.x)),
        minY: Math.min(...visible.map(node => node.y)),
        maxY: Math.max(...visible.map(node => node.y))
      };
    }

    function refreshGraph({ fit = false } = {}) {
      state.renderedConceptIds = computeRenderedConcepts();
      refreshRenderedEdges();
      layout();
      renderInspector();
      updateGraphStatus();
      if (fit) fitView();
      else draw();
    }

    function fitView() {
      const box = bounds();
      const padding = 80;
      const width = Math.max(1, box.maxX - box.minX);
      const height = Math.max(1, box.maxY - box.minY);
      const scale = Math.max(.18, Math.min(2.3, Math.min((state.width - padding * 2) / width, (state.height - padding * 2) / height)));
      state.view.k = scale;
      state.view.x = state.width / 2 - ((box.minX + box.maxX) / 2) * scale;
      state.view.y = state.height / 2 - ((box.minY + box.maxY) / 2) * scale;
      draw();
    }

    function resize() {
      const rect = stage.getBoundingClientRect();
      state.width = Math.max(1, rect.width);
      state.height = Math.max(1, rect.height);
      state.dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(state.width * state.dpr);
      canvas.height = Math.round(state.height * state.dpr);
      canvas.style.width = `${state.width}px`;
      canvas.style.height = `${state.height}px`;
      fitView();
    }

    function drawMapping(mapping, source, target, highlighted) {
      const color = ringColors[mapping.semanticRing];
      const subdued = state.selected && !highlighted;
      const edgeColor = subdued ? subduedEdgeColor : color;
      const edgeAlpha = highlighted ? .95 : subdued ? .72 : .52;
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = edgeColor;
      ctx.globalAlpha = edgeAlpha;
      ctx.lineWidth = (highlighted ? 2.4 : 1.5) / state.view.k;
      ctx.setLineDash([7 / state.view.k, 5 / state.view.k]);
      ctx.stroke();
      ctx.setLineDash([]);
      if (mappingRelationKind(mapping).startsWith("directed")) {
        const angle = Math.atan2(target.y - source.y, target.x - source.x);
        const tipOffset = (conceptRadius(target) + 2.5) / state.view.k;
        const arrowLength = 9 / state.view.k;
        const arrowWidth = 4.5 / state.view.k;
        const tipX = target.x - Math.cos(angle) * tipOffset;
        const tipY = target.y - Math.sin(angle) * tipOffset;
        const baseX = tipX - Math.cos(angle) * arrowLength;
        const baseY = tipY - Math.sin(angle) * arrowLength;
        ctx.beginPath();
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(baseX + Math.sin(angle) * arrowWidth, baseY - Math.cos(angle) * arrowWidth);
        ctx.lineTo(baseX - Math.sin(angle) * arrowWidth, baseY + Math.cos(angle) * arrowWidth);
        ctx.closePath();
        ctx.fillStyle = edgeColor;
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function drawNativeRelations(relations, highlighted) {
      const visible = relations.filter(isNativeRelationVisible);
      if (!visible.length) return;
      const relation = visible[0];
      const source = conceptByViewId.get(relation.subjectViewId);
      const target = conceptByViewId.get(relation.objectViewId);
      const release = releaseById.get(relation.releaseId);
      const subdued = state.selected && !highlighted;
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = subdued
        ? subduedEdgeColor
        : release ? release.color : ringColors[relation.semanticRing];
      ctx.globalAlpha = highlighted ? .92 : subdued ? .72 : .34;
      ctx.lineWidth = (highlighted ? 2.2 : 1.15) / state.view.k;
      ctx.setLineDash([]);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    function drawLabel(concept, radius) {
      const release = releaseById.get(concept.releaseId);
      ctx.font = `${11 / state.view.k}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      const textWidth = ctx.measureText(concept.label).width;
      const x = concept.x + radius + 5 / state.view.k;
      const y = concept.y;
      ctx.fillStyle = "rgba(8, 13, 12, .9)";
      ctx.fillRect(x - 2 / state.view.k, y - 8 / state.view.k, textWidth + 5 / state.view.k, 16 / state.view.k);
      ctx.fillStyle = release ? release.color : "#edf1ed";
      ctx.fillText(concept.label, x, y);
    }

    function drawConcept(concept) {
      const release = releaseById.get(concept.releaseId);
      const radius = conceptRadius(concept) / state.view.k;
      const selected = state.selected === concept.viewId;
      const hovered = state.hover === concept.viewId;
      const searchDimmed = state.query && !state.matches.has(concept.viewId) && !selected;
      ctx.globalAlpha = searchDimmed ? .14 : 1;
      if (concept.selectionReasons.includes("mappingEndpoint")) {
        ctx.beginPath();
        ctx.arc(concept.x, concept.y, radius + 3 / state.view.k, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(233, 185, 95, .42)";
        ctx.lineWidth = 1 / state.view.k;
        ctx.stroke();
      }
      if (selected || hovered) {
        ctx.beginPath();
        ctx.arc(concept.x, concept.y, radius + 5 / state.view.k, 0, Math.PI * 2);
        ctx.fillStyle = selected ? "rgba(233, 185, 95, .2)" : "rgba(140, 211, 199, .15)";
        ctx.fill();
      }
      ctx.beginPath();
      ctx.arc(concept.x, concept.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = release ? release.color : "#edf1ed";
      ctx.fill();
      ctx.strokeStyle = selected ? "#fff3d9" : "rgba(7, 12, 11, .8)";
      ctx.lineWidth = (selected ? 2 : 1) / state.view.k;
      ctx.stroke();
      ctx.globalAlpha = 1;
      if (selected || hovered || (state.matches.has(concept.viewId) && state.matches.size <= 12)) {
        drawLabel(concept, radius);
      }
    }

    function draw() {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(
        state.dpr * state.view.k, 0, 0, state.dpr * state.view.k,
        state.dpr * state.view.x, state.dpr * state.view.y
      );

      const highlightedNativeGroups = [];
      state.renderedNativeGroups.forEach(relations => {
        const highlighted = state.selected && relations.some(
          relation => relation.subjectViewId === state.selected || relation.objectViewId === state.selected
        );
        if (highlighted) highlightedNativeGroups.push(relations);
        else drawNativeRelations(relations, false);
      });
      highlightedNativeGroups.forEach(relations => drawNativeRelations(relations, true));

      const highlightedMappings = [];
      state.renderedMappings.forEach(mapping => {
        const source = conceptByViewId.get(mapping.sourceViewId);
        const target = conceptByViewId.get(mapping.targetViewId);
        const highlighted = state.selected && (mapping.sourceViewId === state.selected || mapping.targetViewId === state.selected);
        if (highlighted) highlightedMappings.push({ mapping, source, target });
        else drawMapping(mapping, source, target, false);
      });
      highlightedMappings.forEach(({ mapping, source, target }) => drawMapping(mapping, source, target, true));

      state.renderedConceptIds.forEach(viewId => {
        if (viewId === state.selected) return;
        const concept = conceptByViewId.get(viewId);
        if (!isConceptVisible(concept)) return;
        drawConcept(concept);
      });
      const selected = state.selected ? conceptByViewId.get(state.selected) : null;
      if (selected && isConceptVisible(selected)) drawConcept(selected);
    }

    function hitTest(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const point = screenToWorld(clientX - rect.left, clientY - rect.top);
      let found = null;
      let distance = Infinity;
      state.renderedConceptIds.forEach(viewId => {
        const concept = conceptByViewId.get(viewId);
        if (!isConceptVisible(concept)) return;
        const dx = concept.x - point.x;
        const dy = concept.y - point.y;
        const candidate = Math.hypot(dx, dy);
        const threshold = conceptRadius(concept) / state.view.k + 8 / state.view.k;
        if (candidate <= threshold && candidate < distance) {
          found = concept;
          distance = candidate;
        }
      });
      return found;
    }

    function zoomAt(factor, x = state.width / 2, y = state.height / 2) {
      const before = screenToWorld(x, y);
      state.view.k = Math.max(.15, Math.min(8, state.view.k * factor));
      state.view.x = x - before.x * state.view.k;
      state.view.y = y - before.y * state.view.k;
      draw();
    }

    function roleLabel(concept) {
      const role = concept.selectionReasons.includes("mappingEndpoint")
        ? "Mapping assertion endpoint"
        : concept.selectionReasons.includes("nativeRelationEndpoint")
          ? "Source-native relation endpoint"
        : concept.selectionReasons.includes("releaseRepresentative")
          ? "Concept release sample"
          : "Concept";
      return `${role} · ${ringLabels[concept.semanticRing]} ring`;
    }

    function selectConcept(concept, { fit = false } = {}) {
      state.selected = concept ? concept.viewId : null;
      if (concept && !state.activeReleases.has(concept.releaseId)) state.activeReleases.add(concept.releaseId);
      if (concept && !state.activeRings.has(concept.semanticRing)) state.activeRings.add(concept.semanticRing);
      refreshGraph({ fit });
    }

    function nativeRelationFromSelected(item) {
      if (item.direction === "outgoing") {
        return item.edge.predicateLabel;
      }
      const inverseLabels = new Map([
        ["broader", "narrower"],
        ["narrower", "broader"],
        ["related", "related"],
        ["thesaurus use", "thesaurus used for"],
        ["thesaurus used for", "thesaurus use"]
      ]);
      return inverseLabels.get(item.edge.predicateLabel) || item.edge.predicateLabel;
    }

    function inspectorRelationLabel(item) {
      return item.kind === "native" ? nativeRelationFromSelected(item) : item.edge.relationLabel;
    }

    function groupInspectorLinks(links) {
      const groups = new Map();
      links.forEach(item => {
        const key = item.kind === "native"
          ? `native\u001f${item.other}\u001f${item.edge.releaseId}\u001f${nativeRelationFromSelected(item)}`
          : `mapping\u001f${item.other}\u001f${item.edge.id}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
      });
      return [...groups.values()].sort((left, right) => {
        const leftItem = left[0];
        const rightItem = right[0];
        return leftItem.kind.localeCompare(rightItem.kind)
          || inspectorRelationLabel(leftItem).localeCompare(inspectorRelationLabel(rightItem))
          || conceptByViewId.get(leftItem.other).label.localeCompare(conceptByViewId.get(rightItem.other).label)
          || leftItem.other.localeCompare(rightItem.other);
      });
    }

    function appendMappingEndpoint(container, role, concept) {
      const endpoint = document.createElement("small");
      endpoint.className = "mapping-endpoint";
      const roleLabel = document.createElement("strong");
      roleLabel.textContent = `${role} endpoint — `;
      endpoint.append(
        roleLabel,
        document.createTextNode(`${concept.label} · ${releaseById.get(concept.releaseId).label}`)
      );
      container.append(endpoint);
    }

    function appendReferenceGroup(container, label, values) {
      if (!values.length) return;
      const group = document.createElement("div");
      group.className = "reference-group";
      const heading = document.createElement("b");
      heading.textContent = label;
      group.append(heading);
      values.forEach(value => {
        const reference = document.createElement(/^https?:/.test(value) ? "a" : "code");
        reference.textContent = value;
        if (reference instanceof HTMLAnchorElement) {
          reference.href = value;
          reference.target = "_blank";
          reference.rel = "noreferrer";
        }
        group.append(reference);
      });
      container.append(group);
    }

    function renderMappingReferences(mapping) {
      const details = document.createElement("details");
      details.className = "connection-evidence";
      const summary = document.createElement("summary");
      summary.textContent = "Evidence and proof references";
      details.append(summary);
      [
        ["Mapping assertion", [mapping.id]],
        ["Lifecycle status", [mapping.effectiveLifecycleStatus]],
        ["Supersedes", mapping.supersedes],
        ["Superseded by", mapping.supersededBy],
        ["Direct evidence assertions", mapping.directEvidenceAssertions],
        ["Complete evidence closure", mapping.evidenceAssertions],
        ["External evidence", mapping.externalEvidence],
        ["Candidate records", mapping.candidateIds],
        ["Validation receipts", mapping.validationReceiptIds],
        ["Machine proofs", mapping.machineProofs]
      ].forEach(([label, values]) => appendReferenceGroup(details, label, values));
      const referenceView = document.createElement("a");
      referenceView.className = "evidence-resolver";
      referenceView.href = "atlas-explorer.json";
      referenceView.textContent = "View references in explorer data";
      const canonicalEvidence = document.createElement("a");
      canonicalEvidence.className = "evidence-resolver";
      canonicalEvidence.href = "atlas.nq.gz";
      canonicalEvidence.setAttribute("download", "");
      canonicalEvidence.textContent = "Download canonical Atlas evidence";
      details.append(referenceView, document.createTextNode(" · "), canonicalEvidence);
      return details;
    }

    function hierarchyStepDescription(step) {
      if (step.kind === "mapping") {
        const source = conceptByViewId.get(step.edge.sourceViewId);
        const target = conceptByViewId.get(step.edge.targetViewId);
        return `Source ${source.label} (${releaseById.get(source.releaseId).label}) ${mappingConnector(step.edge)} Target ${target.label} (${releaseById.get(target.releaseId).label})`;
      }
      const subject = conceptByViewId.get(step.edge.subjectViewId);
      const object = conceptByViewId.get(step.edge.objectViewId);
      return `${subject.label} —${step.edge.predicateLabel}→ ${object.label} (${releaseById.get(step.edge.releaseId).label})`;
    }

    function renderHierarchySteps(path) {
      const details = document.createElement("details");
      details.className = "connection-evidence";
      const summary = document.createElement("summary");
      summary.textContent = `Inspect ${formatQuantity(path.length, "direct assertion")}`;
      details.append(summary);
      path.forEach((step, index) => {
        appendReferenceGroup(
          details,
          `Step ${index + 1} · ${step.kind === "mapping" ? "cross-release mapping" : "source-native hierarchy"}`,
          [hierarchyStepDescription(step), step.edge.id]
        );
      });
      return details;
    }

    function renderInspector() {
      const empty = document.getElementById("empty-inspector");
      const content = document.getElementById("inspector-content");
      const inspector = document.getElementById("inspector");
      const concept = state.selected ? conceptByViewId.get(state.selected) : null;
      empty.hidden = Boolean(concept);
      content.hidden = !concept;
      inspector.classList.toggle("open", Boolean(concept));
      if (!concept) return;
      const release = releaseById.get(concept.releaseId);
      const links = adjacency.get(concept.viewId).filter(isLinkEligible);
      const nativeLinks = links.filter(item => item.kind === "native");
      const mappingLinks = links.filter(item => item.kind === "mapping");
      const parents = hierarchyNeighbors(concept.viewId, hierarchyParents);
      const children = hierarchyNeighbors(concept.viewId, hierarchyChildren);
      const ancestors = hierarchyClosure(concept.viewId, hierarchyParents);
      const descendants = hierarchyClosure(concept.viewId, hierarchyChildren);
      const related = new Set(
        nativeLinks
          .filter(item => item.edge.predicateLabel === "related")
          .map(item => item.other)
      );
      document.getElementById("node-role").textContent = roleLabel(concept);
      document.getElementById("node-title").textContent = concept.label;
      document.getElementById("node-release").textContent = release.label;
      document.getElementById("node-swatch").style.setProperty("--node-color", release.color);
      const iri = document.getElementById("node-iri");
      iri.textContent = concept.conceptId;
      if (/^https?:/.test(concept.conceptId)) {
        iri.href = concept.conceptId;
        iri.target = "_blank";
        iri.rel = "noreferrer";
      } else {
        iri.removeAttribute("href");
        iri.removeAttribute("target");
      }
      document.getElementById("node-native-count").textContent = formatNumber(nativeLinks.length);
      document.getElementById("node-mapping-count").textContent = formatNumber(mappingLinks.length);
      document.getElementById("node-parent-count").textContent = formatNumber(parents.length);
      document.getElementById("node-child-count").textContent = formatNumber(children.length);
      document.getElementById("node-ancestor-count").textContent = formatNumber(ancestors.length);
      document.getElementById("node-descendant-count").textContent = formatNumber(descendants.length);
      document.getElementById("node-related-count").textContent = formatNumber(related.size);
      const notation = document.getElementById("notation-value");
      document.getElementById("notation-term").hidden = notation.hidden = !concept.notation;
      notation.textContent = concept.notation || "";
      const definition = document.getElementById("node-definition");
      definition.hidden = !concept.definition;
      definition.textContent = concept.definition ? `Definition — ${concept.definition}` : "";
      const scopeNote = document.getElementById("node-scope-note");
      scopeNote.hidden = !concept.scopeNote;
      scopeNote.textContent = concept.scopeNote ? `Scope note — ${concept.scopeNote}` : "";
      document.getElementById("node-notes").hidden = !(concept.definition || concept.scopeNote);
      const container = document.getElementById("connections");
      container.replaceChildren();
      if (!links.length) {
        const note = document.createElement("p");
        note.className = "hint";
        note.textContent = "No relationships match the active filters.";
        container.append(note);
      }
      groupInspectorLinks(links)
        .forEach(group => {
          const item = group[0];
          const other = conceptByViewId.get(item.other);
          const button = document.createElement("button");
          button.type = "button";
          button.className = "connection";
          button.dataset.sourceAssertionCount = String(group.length);
          const edgeColor = item.kind === "native" ? release.color : ringColors[item.edge.semanticRing];
          button.style.setProperty("--connection-color", edgeColor);
          const name = document.createElement("b");
          name.textContent = other.label;
          const relation = document.createElement("small");
          if (item.kind === "native") {
            const equivalentAssertions = group.length > 1
              ? ` · ${formatQuantity(group.length, "equivalent source assertion")}`
              : "";
            relation.textContent = `${nativeRelationFromSelected(item)} · source-native relationship${equivalentAssertions} · ${releaseById.get(other.releaseId).label}`;
          } else {
            const evidence = item.edge.evidenceClasses.join(", ") || "typed evidence";
            const semantics = mappingRelationKind(item.edge) === "directedHierarchy"
              ? "directed hierarchy source → target"
              : mappingRelationKind(item.edge) === "directed"
                ? "directed source → target"
              : mappingRelationKind(item.edge) === "symmetric"
                ? "symmetric relation with retained endpoint roles"
                : "typed source and target roles";
            relation.textContent = `${item.edge.relationLabel} · ${semantics} · ${ringLabels[item.edge.semanticRing]} mapping · ${evidence}`;
          }
          button.append(name, relation);
          if (item.kind === "mapping") {
            const source = conceptByViewId.get(item.edge.sourceViewId);
            const target = conceptByViewId.get(item.edge.targetViewId);
            appendMappingEndpoint(button, "Source", source);
            const connector = document.createElement("small");
            connector.className = "mapping-endpoint";
            connector.textContent = mappingConnector(item.edge);
            button.append(connector);
            appendMappingEndpoint(button, "Target", target);
          }
          button.addEventListener("click", () => selectConcept(other, { fit: true }));
          const wrapper = document.createElement("div");
          wrapper.className = "connection-group";
          wrapper.append(button);
          if (item.kind === "mapping") wrapper.append(renderMappingReferences(item.edge));
          container.append(wrapper);
        });
      const hierarchySection = document.getElementById("node-hierarchy");
      const hierarchyContainer = document.getElementById("hierarchy-connections");
      hierarchyContainer.replaceChildren();
      const hierarchyRows = [
        ...ancestors.map(item => ({ ...item, direction: "ancestor" })),
        ...descendants.map(item => ({ ...item, direction: "descendant" }))
      ];
      hierarchySection.hidden = !hierarchyRows.length;
      hierarchyRows.slice(0, 120).forEach(item => {
        const wrapper = document.createElement("div");
        wrapper.className = "connection-group";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "connection";
        button.style.setProperty("--connection-color", release.color);
        const name = document.createElement("b");
        name.textContent = item.concept.label;
        const path = document.createElement("small");
        const direction = item.depth === 1
          ? (item.direction === "ancestor" ? "parent" : "child")
          : item.direction;
        const routeKind = item.depth === 1 ? `direct ${direction}` : `inferred ${direction} route`;
        path.textContent = `${routeKind} · ${formatQuantity(item.depth, "asserted step")} · ${hierarchyPathKinds(item.path)}`;
        button.append(name, path);
        button.addEventListener("click", () => selectConcept(item.concept, { fit: true }));
        wrapper.append(button, renderHierarchySteps(item.path));
        hierarchyContainer.append(wrapper);
      });
      if (hierarchyRows.length > 120) {
        const note = document.createElement("p");
        note.className = "hint";
        note.textContent = `${formatNumber(hierarchyRows.length - 120)} additional path results remain searchable by concept.`;
        hierarchyContainer.append(note);
      }
    }

    /* explorer-search-ranking-core:start */
    function editDistanceWithin(left, right, limit) {
      if (Math.abs(left.length - right.length) > limit) return false;
      let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
      for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
        const current = [leftIndex];
        let rowMinimum = current[0];
        for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
          const cost = left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1;
          const value = Math.min(
            previous[rightIndex] + 1,
            current[rightIndex - 1] + 1,
            previous[rightIndex - 1] + cost
          );
          current.push(value);
          rowMinimum = Math.min(rowMinimum, value);
        }
        if (rowMinimum > limit) return false;
        previous = current;
      }
      return previous[right.length] <= limit;
    }

    function scoreSearch(document, query, tokens) {
      const exactLabel = document.labels.find(label => label.normalized === query);
      if (document.displayLabel === query) return { score: 1000, match: "Exact preferred label" };
      if (exactLabel) return { score: 960, match: `Exact label · ${exactLabel.value}` };
      if (document.notation && document.notation === query) return { score: 940, match: "Exact notation" };
      if (document.identifier === query || document.identifierTail === query) return { score: 920, match: "Exact identifier" };
      if (document.displayLabel.startsWith(query)) return { score: 880, match: "Preferred label starts with query" };
      const prefixLabel = document.labels.find(label => label.normalized.startsWith(query));
      if (prefixLabel) return { score: 850, match: `Label starts with query · ${prefixLabel.value}` };
      const tokenPrefixLabel = document.labels.find(label =>
        tokens.every(token => label.tokens.some(value => value.startsWith(token)))
      );
      if (tokenPrefixLabel) {
        const preferred = tokenPrefixLabel.normalized === document.displayLabel;
        return {
          score: preferred ? 820 : 790,
          match: preferred
            ? "All words match preferred-label prefixes"
            : `All words match one label · ${tokenPrefixLabel.value}`
        };
      }
      if (document.displayLabel.includes(query)) return { score: 760, match: "Preferred label contains query" };
      const containedLabel = document.labels.find(label => label.normalized.includes(query));
      if (containedLabel) return { score: 720, match: `Label contains query · ${containedLabel.value}` };
      if (document.notation && document.notation.includes(query)) return { score: 680, match: "Notation contains query" };
      if (document.identifier.includes(query) || document.identifierTail.includes(query)) {
        return { score: 640, match: "Identifier contains query" };
      }
      if (tokens.every(token => document.sourceFacts.includes(token))) return { score: 520, match: "Source or release fact" };
      if (tokens.every(token => document.notes.includes(token))) return { score: 420, match: "Definition or scope note" };
      const fuzzyLabel = query.length >= 4
        ? document.labels.find(label => tokens.every(token => label.tokens.some(value =>
          editDistanceWithin(token, value, token.length >= 8 ? 2 : 1)
        )))
        : null;
      if (fuzzyLabel) {
        const preferred = fuzzyLabel.normalized === document.displayLabel;
        return {
          score: preferred ? 300 : 260,
          match: preferred ? "Possible preferred-label spelling match" : `Possible label spelling match · ${fuzzyLabel.value}`
        };
      }
      return null;
    }

    function rankSearchDocuments(documents, queryValue, semanticRing) {
      const query = normalizeSearch(queryValue);
      if (!query) return [];
      const tokens = query.split(" ").filter(Boolean);
      return documents
        .filter(document => document.concept.semanticRing === semanticRing)
        .map(document => {
          const score = scoreSearch(document, query, tokens);
          return score ? { document, ...score } : null;
        })
        .filter(Boolean)
        .sort((left, right) => right.score - left.score
          || (left.document.concept.viewId < right.document.concept.viewId ? -1
            : left.document.concept.viewId > right.document.concept.viewId ? 1 : 0));
    }
    /* explorer-search-ranking-core:end */

    function updateActiveSearchResult(index) {
      const buttons = [...resultBox.querySelectorAll(".result")];
      if (!buttons.length) {
        state.activeSearchIndex = -1;
        search.removeAttribute("aria-activedescendant");
        return;
      }
      state.activeSearchIndex = Math.max(0, Math.min(index, buttons.length - 1));
      buttons.forEach((button, buttonIndex) => {
        const active = buttonIndex === state.activeSearchIndex;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
      });
      const active = buttons[state.activeSearchIndex];
      search.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    }

    function chooseSearchResult(index) {
      const result = state.searchResults[index];
      if (!result) return;
      selectConcept(conceptByViewId.get(result.document.concept.viewId), { fit: true });
      search.setAttribute("aria-expanded", "false");
      resultBox.hidden = true;
    }

    function renderSearch({ focusMatches = false, refresh = true } = {}) {
      const query = normalizeSearch(search.value);
      state.query = query;
      state.searchResults = rankSearchDocuments(
        searchDocuments.filter(document => isConceptEligible(document.concept)),
        query,
        state.activeSearchRing
      );
      state.matches = new Set(state.searchResults.map(result => result.document.concept.viewId));
      state.activeSearchIndex = -1;
      if (focusMatches) state.selected = null;
      resultBox.replaceChildren();
      resultBox.hidden = !query;
      const visibleResults = state.searchResults.slice(0, maxSearchResults);
      visibleResults.forEach((result, index) => {
        const row = result.document.concept;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "result";
        button.id = `search-result-${index}`;
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        const label = document.createElement("span");
        label.textContent = row.label;
        const source = document.createElement("small");
        source.textContent = `${releaseById.get(row.releaseId).label} · ${ringLabels[row.semanticRing]} ring`;
        const match = document.createElement("small");
        match.className = "match";
        match.textContent = result.match;
        button.append(label, source, match);
        button.addEventListener("click", () => chooseSearchResult(index));
        resultBox.append(button);
      });
      if (query) {
        const note = document.createElement("small");
        note.className = "result-summary";
        note.textContent = state.searchResults.length
          ? `${ringLabels[state.activeSearchRing]} ring · ${formatQuantity(state.searchResults.length, "matching concept")} · ${formatNumber(visibleResults.length)} listed`
          : `No ${ringLabels[state.activeSearchRing].toLocaleLowerCase()}-ring concepts match the search and active filters.`;
        resultBox.append(note);
      }
      search.setAttribute("aria-expanded", String(Boolean(query && visibleResults.length)));
      if (refresh) refreshGraph({ fit: focusMatches });
    }

    function filtersChanged() {
      const selected = state.selected ? conceptByViewId.get(state.selected) : null;
      if (selected && !isConceptEligible(selected)) state.selected = null;
      renderSearch({ refresh: false });
      renderPlanningRows();
      refreshGraph({ fit: true });
    }

    function compactFacetValue(value) {
      if (value.length <= 52) return value;
      return `${value.slice(0, 24)}…${value.slice(-22)}`;
    }

    function appendFacetSelect(container, field, labelText, values, onChange) {
      if (!values.length) return null;
      const label = document.createElement("label");
      label.className = "facet-control";
      const caption = document.createElement("span");
      caption.textContent = labelText;
      const select = document.createElement("select");
      select.dataset.facet = field;
      select.setAttribute("aria-label", `Filter by ${labelText.toLocaleLowerCase()}`);
      const all = document.createElement("option");
      all.value = "";
      all.textContent = `All ${labelText.toLocaleLowerCase()} values`;
      select.append(all);
      values.forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = compactFacetValue(value);
        option.title = value;
        select.append(option);
      });
      select.addEventListener("change", () => onChange(select.value));
      label.append(caption, select);
      container.append(label);
      return select;
    }

    function renderSearchRingControl() {
      availableSearchRings.forEach(ring => {
        const option = document.createElement("option");
        option.value = ring;
        option.textContent = `${ringLabels[ring]} ring`;
        searchRing.append(option);
      });
      searchRing.value = state.activeSearchRing;
      searchRing.addEventListener("change", () => {
        state.activeSearchRing = searchRing.value;
        renderSearch({ focusMatches: true });
      });
    }

    function planningRowEligible(row) {
      return planningRowEligibleForState(row, state);
    }

    function renderPlanningRows() {
      if (!("planningIndex" in data.releaseContext)) return;
      const rows = data.releaseContext.planningRows.filter(planningRowEligible);
      planningRows.replaceChildren();
      rows.forEach(row => {
        const item = document.createElement("div");
        item.className = "planning-row";
        const heading = document.createElement("b");
        heading.textContent = `${row.resourceId} · ${row.disposition}`;
        const source = document.createElement("small");
        const participation = row.atlasParticipation ? ` · ${row.atlasParticipation}` : "";
        source.textContent = `${row.sourceModule} · ${ringLabels[row.semanticRing]}${participation} · ${row.planningStatus}`;
        const reason = document.createElement("small");
        reason.textContent = row.reason;
        item.append(heading, source, reason);
        planningRows.append(item);
      });
      document.getElementById("planning-row-count").textContent = `${formatNumber(rows.length)} shown · ${formatNumber(data.releaseContext.planningRows.length)} exact planning rows`;
    }

    function renderFacetFilters() {
      conceptFacetDefinitions.forEach(([field, label]) => {
        appendFacetSelect(conceptFacetFilters, field, label, data.facets[field], value => {
          state.activeConceptFacets[field] = value;
          filtersChanged();
        });
      });
      appendFacetSelect(
        mappingFacetFilters,
        "mappingPredicates",
        "Mapping predicate",
        data.facets.mappingPredicates,
        value => {
          state.activeMappingPredicate = value;
          filtersChanged();
        }
      );
      appendFacetSelect(
        mappingFacetFilters,
        "mappingLifecycleStatuses",
        "Mapping lifecycle",
        data.facets.mappingLifecycleStatuses,
        value => {
          state.activeMappingLifecycleStatus = value;
          filtersChanged();
        }
      );
      appendFacetSelect(
        mappingFacetFilters,
        "evidenceClasses",
        "Evidence class",
        data.facets.evidenceClasses,
        value => {
          state.activeEvidenceClass = value;
          filtersChanged();
        }
      );
    }

    function renderReleaseContext() {
      if (!("planningIndex" in data.releaseContext)) return;
      document.getElementById("release-context-section").hidden = false;
      document.getElementById("release-context-summary").textContent = `${formatQuantity(data.releaseContext.sourceApprovals.length, "approved source release")} · ${formatQuantity(data.releaseContext.planningRows.length, "disposed planning row")}`;
      const approvals = document.getElementById("source-approvals");
      data.releaseContext.sourceApprovals.forEach(approval => {
        const item = document.createElement("div");
        item.className = "planning-row";
        const heading = document.createElement("b");
        heading.textContent = `${releaseById.get(approval.releaseId)?.label || identifierTail(approval.releaseId)} · approved`;
        const source = document.createElement("small");
        source.textContent = `${ringLabels[approval.semanticRing]} · ${shortId(approval.manifestDigest)}`;
        item.append(heading, source);
        approvals.append(item);
      });
      appendFacetSelect(
        planningFacetFilters,
        "planningDispositions",
        "Planning disposition",
        data.facets.planningDispositions,
        value => {
          state.activePlanningDisposition = value;
          renderPlanningRows();
        }
      );
      renderPlanningRows();
    }

    function renderFilters() {
      data.conceptReleases.forEach(release => {
        const meta = releaseById.get(release.releaseId);
        const label = document.createElement("label");
        label.className = "filter release-filter";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.dataset.release = release.releaseId;
        input.setAttribute("aria-label", `${release.label} release, ${formatQuantity(release.shownConceptCount, "concept")}`);
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.setProperty("--swatch", meta.color);
        const text = document.createElement("span");
        text.className = "label";
        text.textContent = release.label;
        const count = document.createElement("small");
        count.textContent = formatQuantity(release.shownConceptCount, "concept");
        label.append(input, swatch, text, count);
        releaseFilters.append(label);
        input.addEventListener("change", () => {
          if (input.checked) state.activeReleases.add(release.releaseId);
          else state.activeReleases.delete(release.releaseId);
          filtersChanged();
        });
      });

      const conceptCountByRing = new Map(ringOrder.map(ring => [
        ring,
        data.concepts.filter(concept => concept.semanticRing === ring).length
      ]));
      ringOrder.forEach(ring => {
        const label = document.createElement("label");
        label.className = "filter release-filter";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.dataset.ring = ring;
        input.setAttribute("aria-label", `${ringLabels[ring]} ring, ${formatQuantity(conceptCountByRing.get(ring), "concept")}`);
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.setProperty("--swatch", ringColors[ring]);
        const text = document.createElement("span");
        text.className = "label";
        text.textContent = ringLabels[ring];
        const count = document.createElement("small");
        count.textContent = formatQuantity(conceptCountByRing.get(ring), "concept");
        label.append(input, swatch, text, count);
        ringFilters.append(label);
        input.addEventListener("change", () => {
          if (input.checked) state.activeRings.add(ring);
          else state.activeRings.delete(ring);
          filtersChanged();
        });
      });

      nativePredicateOrder.forEach(predicate => {
        const rows = data.nativeRelations.filter(relation => relation.predicate === predicate);
        const label = document.createElement("label");
        label.className = "filter relation-filter";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.dataset.nativePredicate = predicate;
        input.setAttribute("aria-label", `${rows[0] ? rows[0].predicateLabel : predicate.split("#").pop()}, ${formatQuantity(rows.length, "assertion")}`);
        const key = document.createElement("span");
        key.className = "edge-key";
        key.style.setProperty("--edge-color", "#9ba8a2");
        const text = document.createElement("span");
        text.className = "filter-copy";
        const name = document.createElement("span");
        name.className = "label";
        name.textContent = rows[0] ? rows[0].predicateLabel : predicate.split("#").pop();
        const count = document.createElement("small");
        count.textContent = formatQuantity(rows.length, "assertion");
        text.append(name, count);
        label.append(input, key, text);
        nativeFilters.append(label);
        input.addEventListener("change", () => {
          if (input.checked) state.activeNativePredicates.add(predicate);
          else state.activeNativePredicates.delete(predicate);
          filtersChanged();
        });
      });

      const mappingLabel = document.createElement("label");
      mappingLabel.className = "filter relation-filter";
      const mappingInput = document.createElement("input");
      mappingInput.type = "checkbox";
      mappingInput.checked = true;
      mappingInput.dataset.mappingAssertions = "all";
      mappingInput.setAttribute("aria-label", `Qualified mappings, ${formatQuantity(data.mappingAssertions.length, "assertion")}`);
      const mappingKey = document.createElement("span");
      mappingKey.className = "edge-key mapping";
      mappingKey.style.setProperty("--edge-color", "#9ba8a2");
      const mappingText = document.createElement("span");
      mappingText.className = "filter-copy";
      const mappingName = document.createElement("span");
      mappingName.className = "label";
      mappingName.textContent = "Qualified mappings";
      const mappingCount = document.createElement("small");
      mappingCount.textContent = formatQuantity(data.mappingAssertions.length, "assertion");
      mappingText.append(mappingName, mappingCount);
      mappingLabel.append(mappingInput, mappingKey, mappingText);
      mappingFilters.append(mappingLabel);
      mappingInput.addEventListener("change", () => {
        state.mappingsActive = mappingInput.checked;
        filtersChanged();
      });
    }

    function updateGraphStatus() {
      const renderedNativeAssertions = state.renderedNativeGroups.reduce(
        (total, relations) => total + relations.length,
        0
      );
      const renderedConceptCount = state.renderedConceptIds.size;
      const mode = state.selected
        ? `Selected ${conceptByViewId.get(state.selected).label}`
        : state.query
          ? "Search matches"
          : "Relationship overview";
      graphStatus.textContent = renderedConceptCount
        ? `${mode} · ${formatQuantity(renderedConceptCount, "concept")} · ${formatQuantity(renderedNativeAssertions, "native assertion")} · ${formatQuantity(state.renderedMappings.length, "mapping")}`
        : "No concepts match the active filters.";
      document.getElementById("view-count").textContent = `${formatNumber(renderedConceptCount)} rendered · ${formatNumber(state.renderLimit)} limit · ${formatNumber(data.summary.shownConceptCount)} searchable concepts`;
    }

    function explorerScopeText() {
      return data.summary.truncated
        ? `This index contains ${formatNumber(data.summary.shownConceptCount)} of ${formatNumber(data.summary.availableConceptCount)} concepts.`
        : `All ${formatNumber(data.summary.shownConceptCount)} concepts and ${formatNumber(data.summary.shownNativeRelationCount)} native assertions are searchable.`;
    }

    function syncRenderLimitControls() {
      renderLimitRange.value = String(state.renderLimit);
      renderLimitNumber.value = String(state.renderLimit);
      renderLimitRange.setAttribute("aria-valuetext", `${formatQuantity(state.renderLimit, "concept")} maximum`);
      document.getElementById("selection-note").textContent = `${explorerScopeText()} The graph draws at most ${formatNumber(state.renderLimit)} concepts; active filters may produce fewer.`;
    }

    function setRenderLimit(value, { refresh = true } = {}) {
      const parsed = Number.parseInt(String(value), 10);
      const next = Number.isFinite(parsed)
        ? Math.max(1, Math.min(renderCapacity, parsed))
        : state.renderLimit;
      const changed = next !== state.renderLimit;
      state.renderLimit = next;
      syncRenderLimitControls();
      if (!refresh || !changed) return;
      if (renderLimitFrame !== null) cancelAnimationFrame(renderLimitFrame);
      renderLimitFrame = requestAnimationFrame(() => {
        renderLimitFrame = null;
        refreshGraph({ fit: true });
      });
    }

    function populateText() {
      document.getElementById("short-id").textContent = shortId(data.atlas.assetId);
      document.getElementById("metric-releases").textContent = formatNumber(data.atlas.counts.conceptReleases);
      document.getElementById("metric-quads").textContent = formatNumber(data.atlas.quadCount);
      document.getElementById("metric-native").textContent = formatNumber(data.summary.availableNativeRelationCount);
      renderLimitRange.max = String(renderCapacity);
      renderLimitNumber.max = String(renderCapacity);
      document.getElementById("render-limit-max").textContent = formatNumber(data.summary.shownConceptCount);
      syncRenderLimitControls();
      document.getElementById("pin-id").textContent = data.atlas.assetId;
      document.getElementById("pin-manifest").textContent = data.atlas.manifestDigest;
      document.getElementById("pin-output").textContent = data.atlas.distributionDigest;
      document.getElementById("pin-selection").textContent = data.selectionPolicy.id;
      if ("planningIndex" in data.releaseContext) {
        document.getElementById("pin-index-label").hidden = false;
        document.getElementById("pin-index").hidden = false;
        document.getElementById("pin-index").textContent = `${data.releaseContext.planningIndex.id} · ${data.releaseContext.planningIndex.fileDigest}`;
        document.getElementById("pin-decision-label").hidden = false;
        document.getElementById("pin-decision").hidden = false;
        document.getElementById("pin-decision").textContent = `${data.releaseContext.publicationDecision.id} · ${data.releaseContext.publicationDecision.recordDigest}`;
        document.getElementById("index-download").hidden = false;
      }
    }

    canvas.addEventListener("pointerdown", event => {
      canvas.setPointerCapture(event.pointerId);
      const hit = hitTest(event.clientX, event.clientY);
      if (hit) {
        selectConcept(hit);
      } else {
        state.panning = true;
        state.dragStart = { x: event.clientX, y: event.clientY, viewX: state.view.x, viewY: state.view.y };
        canvas.classList.add("panning");
      }
    });
    canvas.addEventListener("pointermove", event => {
      if (state.panning && state.dragStart) {
        state.view.x = state.dragStart.viewX + event.clientX - state.dragStart.x;
        state.view.y = state.dragStart.viewY + event.clientY - state.dragStart.y;
        draw();
        return;
      }
      const hit = hitTest(event.clientX, event.clientY);
      state.hover = hit ? hit.viewId : null;
      if (hit) {
        const rect = stage.getBoundingClientRect();
        tooltip.replaceChildren();
        const name = document.createTextNode(hit.label);
        const source = document.createElement("small");
        source.textContent = releaseById.get(hit.releaseId).label;
        tooltip.append(name, source);
        tooltip.style.left = `${event.clientX - rect.left}px`;
        tooltip.style.top = `${event.clientY - rect.top}px`;
        tooltip.hidden = false;
      } else {
        tooltip.hidden = true;
      }
      draw();
    });
    canvas.addEventListener("pointerup", event => {
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      state.panning = false;
      state.dragStart = null;
      canvas.classList.remove("panning");
    });
    canvas.addEventListener("pointerleave", () => {
      state.hover = null;
      tooltip.hidden = true;
      draw();
    });
    canvas.addEventListener("wheel", event => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      zoomAt(event.deltaY < 0 ? 1.12 : .89, event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });
    canvas.addEventListener("keydown", event => {
      const step = 32;
      if (event.key === "+" || event.key === "=") zoomAt(1.2);
      else if (event.key === "-") zoomAt(.83);
      else if (event.key === "ArrowLeft") state.view.x += step;
      else if (event.key === "ArrowRight") state.view.x -= step;
      else if (event.key === "ArrowUp") state.view.y += step;
      else if (event.key === "ArrowDown") state.view.y -= step;
      else return;
      event.preventDefault();
      draw();
    });
    document.getElementById("zoom-in").addEventListener("click", () => zoomAt(1.25));
    document.getElementById("zoom-out").addEventListener("click", () => zoomAt(.8));
    document.getElementById("fit-view").addEventListener("click", fitView);
    renderLimitRange.addEventListener("input", event => setRenderLimit(event.currentTarget.value));
    renderLimitNumber.addEventListener("change", event => setRenderLimit(event.currentTarget.value));
    renderLimitNumber.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      setRenderLimit(event.currentTarget.value);
      event.currentTarget.select();
    });
    document.getElementById("toggle-controls").addEventListener("click", event => {
      const controls = document.getElementById("controls");
      controls.classList.toggle("open");
      event.currentTarget.setAttribute("aria-label", controls.classList.contains("open") ? "Hide filters" : "Show filters");
    });
    document.getElementById("copy-iri").addEventListener("click", async event => {
      if (!state.selected) return;
      try {
        await navigator.clipboard.writeText(conceptByViewId.get(state.selected).conceptId);
        event.currentTarget.textContent = "Copied";
        window.setTimeout(() => { event.currentTarget.textContent = "Copy IRI"; }, 1200);
      } catch (_) {
        event.currentTarget.textContent = "Copy unavailable";
      }
    });
    search.addEventListener("input", () => renderSearch({ focusMatches: true }));
    search.addEventListener("focus", () => {
      if (state.query) {
        resultBox.hidden = false;
        search.setAttribute("aria-expanded", String(Boolean(state.searchResults.length)));
      }
    });
    search.addEventListener("keydown", event => {
      const visibleCount = Math.min(maxSearchResults, state.searchResults.length);
      if (event.key === "ArrowDown" && visibleCount) {
        event.preventDefault();
        updateActiveSearchResult(state.activeSearchIndex + 1);
      } else if (event.key === "ArrowUp" && visibleCount) {
        event.preventDefault();
        updateActiveSearchResult(state.activeSearchIndex <= 0 ? visibleCount - 1 : state.activeSearchIndex - 1);
      } else if (event.key === "Enter" && visibleCount) {
        event.preventDefault();
        chooseSearchResult(state.activeSearchIndex < 0 ? 0 : state.activeSearchIndex);
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        search.value = "";
        renderSearch({ focusMatches: true });
      }
    });
    document.getElementById("reset-filters").addEventListener("click", () => {
      state.activeReleases = new Set(data.conceptReleases.map(release => release.releaseId));
      state.activeNativePredicates = new Set(nativePredicateOrder);
      state.activeRings = new Set(ringOrder);
      state.activeSearchRing = defaultSearchRing;
      state.activeConceptFacets = Object.fromEntries(conceptFacetDefinitions.map(([field]) => [field, ""]));
      state.activeMappingPredicate = "";
      state.activeMappingLifecycleStatus = "";
      state.activeEvidenceClass = "";
      state.activePlanningDisposition = "";
      state.mappingsActive = true;
      state.selected = null;
      search.value = "";
      document.querySelectorAll("#controls input[type=checkbox]").forEach(input => { input.checked = true; });
      document.querySelectorAll("#controls select:not(#search-ring)").forEach(select => { select.value = ""; });
      searchRing.value = defaultSearchRing;
      renderPlanningRows();
      renderSearch({ focusMatches: true });
    });
    window.addEventListener("keydown", event => {
      if (event.key === "/" && document.activeElement !== search) {
        event.preventDefault();
        search.focus();
      }
      if (event.key === "Escape") {
        search.value = "";
        renderSearch({ focusMatches: true });
      }
    });
    new ResizeObserver(resize).observe(stage);

    populateText();
    renderSearchRingControl();
    renderFacetFilters();
    renderFilters();
    renderReleaseContext();
    renderSearch({ refresh: false });
    refreshGraph();
    resize();
    requestAnimationFrame(() => canvas.classList.add("ready"));
  })();
  </script>
</body>
</html>
"""


def _safe_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _default_search_ring(model: Mapping[str, Any]) -> str:
    concepts = cast(Sequence[Mapping[str, Any]], model["concepts"])
    available = {cast(str, concept["semanticRing"]) for concept in concepts}
    return next((ring for ring in _RING_ORDER if ring in available), "subject")


def render_atlas_explorer(model: Mapping[str, Any]) -> str:
    """Validate Atlas 2.0 explorer data and return one self-contained HTML file."""

    if not isinstance(model, Mapping):
        raise AtlasExplorerError("atlas explorer must be an object")
    _validate_model(model)
    title = cast(str, model["title"])
    return _Template(_HTML).substitute(
        title=html.escape(title, quote=True),
        atlas_data=_safe_json(model),
        default_search_ring=_default_search_ring(model),
        explorer_filter_semantics=json.dumps(
            EXPLORER_FILTER_SEMANTICS,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        planning_filter_semantics=json.dumps(
            PLANNING_FILTER_SEMANTICS,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


__all__ = [
    "EXPLORER_FILTER_SEMANTICS",
    "EXPLORER_SCHEMA_VERSION",
    "EXPLORER_TYPE",
    "PLANNING_FILTER_SEMANTICS",
    "AtlasExplorerError",
    "render_atlas_explorer",
]

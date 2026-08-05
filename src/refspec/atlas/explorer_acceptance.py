"""Executable acceptance evidence for one complete Atlas explorer.

The gate independently counts every advertised filter value, reconciles the
complete explorer to generic Atlas query endpoints, proves every assertion is
reachable through its endpoints and filters, and executes a reviewed search
corpus before a public release may pass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from typing_extensions import Self

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)

from .explorer import (
    EXPLORER_FILTER_SEMANTICS,
    EXPLORER_SCHEMA_VERSION,
    EXPLORER_TYPE,
    PLANNING_FILTER_SEMANTICS,
    render_atlas_explorer,
)
from .model import VocabularyAtlasAsset, VocabularyAtlasError
from .queries import VocabularyAtlasQueries

EXPLORER_ACCEPTANCE_TYPE = "VocabularyAtlasExplorerAcceptance"
EXPLORER_ACCEPTANCE_VERSION = "2.0"
EXPLORER_SEARCH_CORPUS_TYPE = "VocabularyAtlasExplorerSearchCorpus"
EXPLORER_SEARCH_CORPUS_VERSION = "2.0"

ExplorerAcceptanceMode = Literal["publicV1", "baselineEvidenceRc"]

_RINGS = ("subject", "entity", "value", "legalIdentity")
_RING_ORDER = {ring: index for index, ring in enumerate(_RINGS)}
_CONCEPT_FACETS = (
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
_MODEL_FACETS = _CONCEPT_FACETS + (
    "nativePredicates",
    "mappingPredicates",
    "mappingLifecycleStatuses",
    "evidenceClasses",
    "planningDispositions",
)
_SEARCH_CATEGORIES = (
    "exactIdentifier",
    "exactPreferredLabel",
    "exactNotation",
    "definitionOrScopeNote",
    "alias",
    "recognizedVariant",
    "normalizedPunctuationSpacing",
    "usefulPrefix",
    "reviewedOneEditTypo",
)
_CORPUS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "reviewedBy",
        "reviewedAt",
        "releaseIds",
        "cases",
        "aggregateCases",
    }
)
_AGGREGATE_CASE_FIELDS = frozenset(
    {
        "id",
        "semanticRing",
        "category",
        "query",
        "expectedReleaseId",
        "expectedResultCount",
        "expectedViewIdDigest",
        "expectedMatch",
    }
)
_CASE_FIELDS = frozenset(
    {
        "id",
        "semanticRing",
        "category",
        "query",
        "expectedReleaseId",
        "expectedConceptId",
        "maximumRank",
    }
)
_ACCEPTANCE_ID_PREFIX = "urn:ref:vocabulary-atlas-explorer-acceptance:"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class ExplorerAcceptanceError(ValueError):
    """The explorer, reviewed corpus, or derived acceptance evidence differs."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise ExplorerAcceptanceError(str(error)) from error
    return canonical_json_bytes(plain)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExplorerAcceptanceError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ExplorerAcceptanceError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ExplorerAcceptanceError(f"{label} must be non-empty trimmed text")
    return value


def _iri(value: object, label: str) -> str:
    result = _text(value, label)
    if absolute_uri_issue(result) is not None:
        raise ExplorerAcceptanceError(f"{label} must be a safe absolute IRI")
    return result


def _count(value: object, label: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise ExplorerAcceptanceError(f"{label} must be a {qualifier} integer")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ExplorerAcceptanceError(
            f"{label} fields differ; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _normalize_search(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    unaccented = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("M")
    )
    folded = unaccented.lower()
    return " ".join("".join(character if character.isalnum() else " " for character in folded).split())


def _identifier_tail(value: str) -> str:
    parts = tuple(part for part in re.split(r"[/#:]", value) if part)
    return parts[-1] if parts else value


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _within_edit_distance(left: str, right: str, limit: int) -> bool:
    return abs(len(left) - len(right)) <= limit and _edit_distance(left, right) <= limit


def _search_documents(explorer: Mapping[str, Any]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(explorer.get("concepts"), "explorer concepts")):
        concept = _mapping(raw, f"explorer concepts[{index}]")
        label = _text(concept.get("label"), f"explorer concepts[{index}].label")
        labels = list(
            dict.fromkeys(
                [
                    label,
                    *(
                        _text(value, f"explorer concepts[{index}].searchLabels[]")
                        for value in _sequence(
                            concept.get("searchLabels", []),
                            f"explorer concepts[{index}].searchLabels",
                        )
                    ),
                ]
            )
        )
        normalized_labels = [
            {
                "value": value,
                "normalized": _normalize_search(value),
                "tokens": _normalize_search(value).split(),
            }
            for value in labels
        ]
        source_facts = " ".join(
            _text(value, f"explorer concepts[{index}].{field}[]")
            for field in _CONCEPT_FACETS
            for value in _sequence(
                concept.get(field),
                f"explorer concepts[{index}].{field}",
            )
        )
        concept_id = _iri(
            concept.get("conceptId"),
            f"explorer concepts[{index}].conceptId",
        )
        documents.append(
            {
                "concept": concept,
                "labels": normalized_labels,
                "displayLabel": _normalize_search(label),
                "notation": _normalize_search(concept.get("notation", "")),
                "identifier": _normalize_search(concept_id),
                "identifierTail": _normalize_search(_identifier_tail(concept_id)),
                "notes": _normalize_search(
                    " ".join(
                        str(concept.get(field, ""))
                        for field in ("definition", "scopeNote")
                    )
                ),
                "sourceFacts": _normalize_search(source_facts),
            }
        )
    return documents


def _search_feature_coverage(explorer: Mapping[str, Any]) -> list[dict[str, Any]]:
    documents = _search_documents(explorer)
    feature_fields = {
        "sourceIdentifier": "identifier",
        "sourceFact": "sourceFacts",
        "exactNotation": "notation",
        "definitionOrScopeNote": "notes",
    }
    result: list[dict[str, Any]] = []
    for feature, field in feature_fields.items():
        for ring in _RINGS:
            identifiers = [
                cast(str, _mapping(document["concept"], "search concept")["viewId"])
                for document in documents
                if _mapping(document["concept"], "search concept").get(
                    "semanticRing"
                )
                == ring
                and bool(document[field])
            ]
            if identifiers:
                result.append(
                    {
                        "feature": feature,
                        "semanticRing": ring,
                        "conceptCount": len(identifiers),
                        "viewIdDigest": _id_digest(identifiers),
                    }
                )
    return result


def _score_search(
    document: Mapping[str, Any],
    query: str,
    tokens: Sequence[str],
) -> tuple[int, str] | None:
    labels = cast(Sequence[Mapping[str, Any]], document["labels"])
    exact_label = next(
        (label for label in labels if label["normalized"] == query),
        None,
    )
    if document["displayLabel"] == query:
        return 1000, "Exact preferred label"
    if exact_label is not None:
        return 960, f"Exact label · {exact_label['value']}"
    if document["notation"] and document["notation"] == query:
        return 940, "Exact notation"
    if document["identifier"] == query or document["identifierTail"] == query:
        return 920, "Exact identifier"
    if cast(str, document["displayLabel"]).startswith(query):
        return 880, "Preferred label starts with query"
    prefix_label = next(
        (label for label in labels if cast(str, label["normalized"]).startswith(query)),
        None,
    )
    if prefix_label is not None:
        return 850, f"Label starts with query · {prefix_label['value']}"
    token_prefix_label = next(
        (
            label
            for label in labels
            if all(
                any(cast(str, value).startswith(token) for value in cast(Sequence[str], label["tokens"]))
                for token in tokens
            )
        ),
        None,
    )
    if token_prefix_label is not None:
        preferred = token_prefix_label["normalized"] == document["displayLabel"]
        return (
            820 if preferred else 790,
            "All words match preferred-label prefixes"
            if preferred
            else f"All words match one label · {token_prefix_label['value']}",
        )
    if query in cast(str, document["displayLabel"]):
        return 760, "Preferred label contains query"
    contained_label = next(
        (label for label in labels if query in cast(str, label["normalized"])),
        None,
    )
    if contained_label is not None:
        return 720, f"Label contains query · {contained_label['value']}"
    if document["notation"] and query in cast(str, document["notation"]):
        return 680, "Notation contains query"
    if query in cast(str, document["identifier"]) or query in cast(str, document["identifierTail"]):
        return 640, "Identifier contains query"
    if all(token in cast(str, document["sourceFacts"]) for token in tokens):
        return 520, "Source or release fact"
    if all(token in cast(str, document["notes"]) for token in tokens):
        return 420, "Definition or scope note"
    fuzzy_label = (
        next(
            (
                label
                for label in labels
                if all(
                    any(
                        _within_edit_distance(token, value, 2 if len(token) >= 8 else 1)
                        for value in cast(Sequence[str], label["tokens"])
                    )
                    for token in tokens
                )
            ),
            None,
        )
        if len(query) >= 4
        else None
    )
    if fuzzy_label is not None:
        preferred = fuzzy_label["normalized"] == document["displayLabel"]
        return (
            300 if preferred else 260,
            "Possible preferred-label spelling match"
            if preferred
            else f"Possible label spelling match · {fuzzy_label['value']}",
        )
    return None


def rank_explorer_search(
    explorer: Mapping[str, Any],
    *,
    semantic_ring: str,
    query: str,
) -> list[dict[str, Any]]:
    """Execute the explorer's ring-isolated deterministic search ranking."""

    if semantic_ring not in _RING_ORDER:
        raise ExplorerAcceptanceError("search semantic ring is unsupported")
    normalized_query = _normalize_search(_text(query, "search query"))
    if not normalized_query:
        raise ExplorerAcceptanceError("search query normalizes to empty text")
    tokens = normalized_query.split()
    results: list[dict[str, Any]] = []
    for document in _search_documents(explorer):
        concept = cast(Mapping[str, Any], document["concept"])
        if concept.get("semanticRing") != semantic_ring:
            continue
        scored = _score_search(document, normalized_query, tokens)
        if scored is None:
            continue
        results.append(
            {
                "viewId": _text(concept.get("viewId"), "search concept viewId"),
                "releaseId": _iri(concept.get("releaseId"), "search concept releaseId"),
                "conceptId": _iri(concept.get("conceptId"), "search concept conceptId"),
                "label": _text(concept.get("label"), "search concept label"),
                "score": scored[0],
                "match": scored[1],
            }
        )
    results.sort(
        key=lambda row: (
            -cast(int, row["score"]),
            cast(str, row["viewId"]),
        )
    )
    return [{**row, "rank": index} for index, row in enumerate(results, start=1)]


def planning_row_eligible(
    row: Mapping[str, Any],
    selections: Mapping[str, object],
) -> bool:
    """Apply the exact planning-row filter table shipped in the explorer."""

    dimensions = {
        cast(str, specification["dimension"])
        for specification in PLANNING_FILTER_SEMANTICS
    }
    if not set(selections) <= dimensions:
        raise ExplorerAcceptanceError("planning filter selections contain an unsupported dimension")
    for specification in PLANNING_FILTER_SEMANTICS:
        dimension = cast(str, specification["dimension"])
        row_field = cast(str, specification["rowField"])
        operator = specification["operator"]
        selected = selections.get(dimension)
        if operator == "setContains":
            if not isinstance(selected, (set, frozenset)):
                raise ExplorerAcceptanceError(
                    f"planning filter {dimension} must be a set selection"
                )
            if row.get(row_field) not in selected:
                return False
        elif operator == "equalsWhenSet":
            if selected and row.get(row_field) != selected:
                return False
        else:
            raise ExplorerAcceptanceError(
                f"planning filter {dimension} has an unsupported operator"
            )
    return True


def _value_count_rows(values: Sequence[str], advertised: Sequence[str]) -> list[dict[str, Any]]:
    counts = Counter(values)
    return [{"value": value, "count": counts[value]} for value in advertised]


def _facet_measurements(explorer: Mapping[str, Any]) -> list[dict[str, Any]]:
    concepts = tuple(
        _mapping(value, f"explorer concepts[{index}]")
        for index, value in enumerate(_sequence(explorer.get("concepts"), "explorer concepts"))
    )
    native = tuple(
        _mapping(value, f"explorer nativeRelations[{index}]")
        for index, value in enumerate(
            _sequence(explorer.get("nativeRelations"), "explorer nativeRelations")
        )
    )
    mappings = tuple(
        _mapping(value, f"explorer mappingAssertions[{index}]")
        for index, value in enumerate(
            _sequence(explorer.get("mappingAssertions"), "explorer mappingAssertions")
        )
    )
    releases = tuple(
        _mapping(value, f"explorer conceptReleases[{index}]")
        for index, value in enumerate(
            _sequence(explorer.get("conceptReleases"), "explorer conceptReleases")
        )
    )
    context = _mapping(explorer.get("releaseContext"), "explorer releaseContext")
    planning_rows = tuple(
        _mapping(value, f"explorer releaseContext.planningRows[{index}]")
        for index, value in enumerate(
            _sequence(context.get("planningRows"), "explorer releaseContext.planningRows")
        )
    )
    facets = _mapping(explorer.get("facets"), "explorer facets")
    if set(facets) != set(_MODEL_FACETS):
        raise ExplorerAcceptanceError("explorer facet catalog fields differ")

    measurements = [
        {
            "facet": "semanticRings",
            "recordKind": "concept",
            "values": _value_count_rows(
                [cast(str, concept["semanticRing"]) for concept in concepts],
                [ring for ring in _RINGS if any(concept["semanticRing"] == ring for concept in concepts)],
            ),
        },
        {
            "facet": "releases",
            "recordKind": "concept",
            "values": _value_count_rows(
                [cast(str, concept["releaseId"]) for concept in concepts],
                [cast(str, release["releaseId"]) for release in releases],
            ),
        },
    ]
    for field in _CONCEPT_FACETS:
        advertised = [
            _text(value, f"explorer facets.{field}[]")
            for value in _sequence(facets.get(field), f"explorer facets.{field}")
        ]
        values = [
            _text(value, f"explorer concept.{field}[]")
            for concept in concepts
            for value in _sequence(concept.get(field), f"explorer concept.{field}")
        ]
        if not set(values) <= set(advertised):
            raise ExplorerAcceptanceError(f"explorer {field} facet omits a concept value")
        measurements.append(
            {
                "facet": field,
                "recordKind": "concept",
                "values": _value_count_rows(values, advertised),
            }
        )
    specialized = (
        (
            "nativePredicates",
            "nativeRelation",
            [cast(str, row["predicate"]) for row in native],
        ),
        (
            "mappingPredicates",
            "mappingAssertion",
            [cast(str, row["relation"]) for row in mappings],
        ),
        (
            "mappingLifecycleStatuses",
            "mappingAssertion",
            [cast(str, row["effectiveLifecycleStatus"]) for row in mappings],
        ),
        (
            "evidenceClasses",
            "mappingAssertion",
            [
                cast(str, value)
                for row in mappings
                for value in cast(Sequence[str], row["evidenceClasses"])
            ],
        ),
        (
            "planningDispositions",
            "planningRow",
            [cast(str, row["disposition"]) for row in planning_rows],
        ),
    )
    for field, record_kind, values in specialized:
        advertised = [
            _text(value, f"explorer facets.{field}[]")
            for value in _sequence(facets.get(field), f"explorer facets.{field}")
        ]
        if set(values) != set(advertised):
            raise ExplorerAcceptanceError(f"explorer {field} facet differs from its rows")
        measurements.append(
            {
                "facet": field,
                "recordKind": record_kind,
                "values": _value_count_rows(values, advertised),
            }
        )
    return sorted(measurements, key=lambda row: cast(str, row["facet"]))


def _id_digest(values: Sequence[str]) -> str:
    return sha256_digest(_canonical_bytes(sorted(values)))


def _state_value(state: Mapping[str, Any], path: str) -> object:
    value: object = state
    for field in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(field)
    return value


def _explorer_filter_matches(
    record: Mapping[str, Any],
    specification: Mapping[str, Any],
    state: Mapping[str, Any],
) -> bool:
    selected = _state_value(
        state,
        _text(specification.get("statePath"), "explorer filter statePath"),
    )
    operator = specification.get("operator")
    row_field = specification.get("rowField")
    observed = record.get(row_field) if isinstance(row_field, str) else None
    if operator == "enabled":
        return bool(selected)
    if operator == "setContains":
        return (
            isinstance(selected, Sequence)
            and not isinstance(selected, (str, bytes))
            and observed in selected
        )
    if operator == "equalsWhenSet":
        return not selected or observed == selected
    if operator == "arrayContainsWhenSet":
        return (
            not selected
            or (
                isinstance(observed, Sequence)
                and not isinstance(observed, (str, bytes))
                and selected in observed
            )
        )
    raise ExplorerAcceptanceError(
        f"explorer filter operator {operator!r} is unsupported"
    )


def _explorer_record_eligible(
    record_kind: str,
    record: Mapping[str, Any],
    state: Mapping[str, Any],
    concept_by_view_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    semantics = next(
        (
            _mapping(value, "explorer filter semantics row")
            for value in EXPLORER_FILTER_SEMANTICS
            if value.get("recordKind") == record_kind
        ),
        None,
    )
    if semantics is None:
        raise ExplorerAcceptanceError(
            f"explorer record kind {record_kind!r} is unsupported"
        )
    filters = _sequence(semantics.get("filters"), "explorer filter semantics filters")
    if not all(
        _explorer_filter_matches(
            record,
            _mapping(value, "explorer filter semantics filter"),
            state,
        )
        for value in filters
    ):
        return False
    for endpoint_field in _sequence(
        semantics.get("endpointFields"),
        "explorer filter semantics endpointFields",
    ):
        endpoint = concept_by_view_id.get(cast(str, record.get(endpoint_field)))
        if endpoint is None or not _explorer_record_eligible(
            "concept",
            endpoint,
            state,
            concept_by_view_id,
        ):
            return False
    return True


def _set_state_path(state: dict[str, Any], path: str, value: object) -> None:
    target = state
    fields = path.split(".")
    for field in fields[:-1]:
        nested = target.get(field)
        if not isinstance(nested, dict):
            nested = {}
            target[field] = nested
        target = nested
    target[fields[-1]] = value


def _default_explorer_filter_state(explorer: Mapping[str, Any]) -> dict[str, Any]:
    facets = _mapping(explorer.get("facets"), "explorer facets")
    return {
        "activeReleases": [
            cast(str, _mapping(value, "explorer release")["releaseId"])
            for value in _sequence(
                explorer.get("conceptReleases"),
                "explorer conceptReleases",
            )
        ],
        "activeNativePredicates": [
            _text(value, "explorer facets.nativePredicates[]")
            for value in _sequence(
                facets.get("nativePredicates"),
                "explorer facets.nativePredicates",
            )
        ],
        "activeRings": list(_RINGS),
        "activeConceptFacets": {field: "" for field in _CONCEPT_FACETS},
        "activeMappingPredicate": "",
        "activeMappingLifecycleStatus": "",
        "activeEvidenceClass": "",
        "mappingsActive": True,
    }


def _filter_dimension_values(
    explorer: Mapping[str, Any],
    specification: Mapping[str, Any],
) -> list[object]:
    facets = _mapping(explorer.get("facets"), "explorer facets")
    dimension = cast(str, specification["dimension"])
    operator = specification["operator"]
    if dimension == "release":
        return [
            cast(str, _mapping(value, "explorer release")["releaseId"])
            for value in _sequence(
                explorer.get("conceptReleases"),
                "explorer conceptReleases",
            )
        ]
    if dimension == "ring":
        return [
            ring
            for ring in _RINGS
            if any(
                _mapping(value, "explorer concept").get("semanticRing") == ring
                for value in _sequence(explorer.get("concepts"), "explorer concepts")
            )
        ]
    if dimension in _CONCEPT_FACETS:
        return list(
            _sequence(facets.get(dimension), f"explorer facets.{dimension}")
        )
    facet_by_dimension = {
        "nativePredicate": "nativePredicates",
        "mappingPredicate": "mappingPredicates",
        "mappingLifecycleStatus": "mappingLifecycleStatuses",
        "evidenceClass": "evidenceClasses",
    }
    if dimension in facet_by_dimension:
        field = facet_by_dimension[dimension]
        return list(_sequence(facets.get(field), f"explorer facets.{field}"))
    if operator == "enabled":
        return [False]
    raise ExplorerAcceptanceError(
        f"explorer filter dimension {dimension!r} is unsupported"
    )


def _filter_cases(explorer: Mapping[str, Any]) -> list[dict[str, Any]]:
    base_state = _default_explorer_filter_state(explorer)
    cases: list[dict[str, Any]] = [
        {
            "id": f"default:{record_kind}",
            "recordKind": record_kind,
            "dimension": "default",
            "value": "all",
            "state": _plain(base_state),
        }
        for record_kind in ("concept", "nativeRelation", "mappingAssertion")
    ]
    seen: set[tuple[str, str, str]] = set()
    for raw_semantics in EXPLORER_FILTER_SEMANTICS:
        semantics = _mapping(raw_semantics, "explorer filter semantics")
        record_kind = cast(str, semantics["recordKind"])
        for raw_filter in _sequence(
            semantics.get("filters"),
            "explorer filter semantics filters",
        ):
            specification = _mapping(raw_filter, "explorer filter semantics filter")
            state_path = cast(str, specification["statePath"])
            dimension = cast(str, specification["dimension"])
            record_kinds = [record_kind]
            if record_kind == "concept":
                record_kinds.extend(("nativeRelation", "mappingAssertion"))
            for raw_value in _filter_dimension_values(explorer, specification):
                selected: object = (
                    [raw_value]
                    if specification["operator"] == "setContains"
                    else raw_value
                )
                value_key = json.dumps(
                    selected,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for affected_kind in record_kinds:
                    key = (affected_kind, state_path, value_key)
                    if key in seen:
                        continue
                    seen.add(key)
                    state = cast(dict[str, Any], _plain(base_state))
                    _set_state_path(state, state_path, selected)
                    cases.append(
                        {
                            "id": (
                                f"{affected_kind}:{dimension}:"
                                f"{sha256_digest(_canonical_bytes(selected))[7:19]}"
                            ),
                            "recordKind": affected_kind,
                            "dimension": dimension,
                            "value": _plain(raw_value),
                            "state": state,
                        }
                    )
    return sorted(cases, key=lambda row: cast(str, row["id"]))


def _python_filter_results(
    explorer: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records_by_kind = {
        "concept": _sequence(explorer.get("concepts"), "explorer concepts"),
        "nativeRelation": _sequence(
            explorer.get("nativeRelations"),
            "explorer nativeRelations",
        ),
        "mappingAssertion": _sequence(
            explorer.get("mappingAssertions"),
            "explorer mappingAssertions",
        ),
    }
    concept_by_view_id = {
        cast(str, row["viewId"]): row
        for row in (
            _mapping(value, "explorer concept")
            for value in records_by_kind["concept"]
        )
    }
    semantics_by_kind = {
        cast(str, row["recordKind"]): row
        for row in (
            _mapping(value, "explorer filter semantics")
            for value in EXPLORER_FILTER_SEMANTICS
        )
    }
    results: list[dict[str, Any]] = []
    for case in cases:
        record_kind = cast(str, case["recordKind"])
        semantics = semantics_by_kind[record_kind]
        id_field = cast(str, semantics["idField"])
        state = _mapping(case.get("state"), "explorer filter case state")
        identifiers = [
            _text(record.get(id_field), f"explorer {record_kind} {id_field}")
            for record in (
                _mapping(value, f"explorer {record_kind}")
                for value in records_by_kind[record_kind]
            )
            if _explorer_record_eligible(
                record_kind,
                record,
                state,
                concept_by_view_id,
            )
        ]
        results.append(
            {
                "id": case["id"],
                "recordKind": record_kind,
                "count": len(identifiers),
                "idDigest": _id_digest(identifiers),
            }
        )
    return results


def _extract_javascript_core(html_text: str, name: str) -> str:
    match = re.search(
        rf"/\* {re.escape(name)}:start \*/(.*?)/\* {re.escape(name)}:end \*/",
        html_text,
        flags=re.DOTALL,
    )
    if match is None:
        raise ExplorerAcceptanceError(
            f"shipped explorer omits the marked {name} JavaScript core"
        )
    return match.group(1)


def _run_shipped_javascript(
    explorer: Mapping[str, Any],
    *,
    html_text: str,
    filter_cases: Sequence[Mapping[str, Any]],
    search_cases: Sequence[Mapping[str, Any]],
    aggregate_search_cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    filter_core = _extract_javascript_core(html_text, "explorer-filter-core")
    document_core = _extract_javascript_core(
        html_text,
        "explorer-search-document-core",
    )
    ranking_core = _extract_javascript_core(
        html_text,
        "explorer-search-ranking-core",
    )
    script = "\n".join(  # noqa: FLY002 -- preserves literal JavaScript braces
        (
            'const crypto = require("node:crypto");',
            filter_core,
            document_core,
            ranking_core,
            """
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
const conceptByViewId = Object.fromEntries(input.explorer.concepts.map(row => [row.viewId, row]));
const recordsByKind = {
  concept: input.explorer.concepts,
  nativeRelation: input.explorer.nativeRelations,
  mappingAssertion: input.explorer.mappingAssertions
};
const idFieldByKind = Object.fromEntries(explorerFilterSemantics.map(row => [row.recordKind, row.idField]));
const setContainsStatePaths = [...new Set(explorerFilterSemantics
  .flatMap(row => row.filters)
  .filter(filter => filter.operator === "setContains")
  .map(filter => filter.statePath))];
function setStatePath(state, path, value) {
  const fields = path.split(".");
  let target = state;
  for (const field of fields.slice(0, -1)) target = target[field];
  target[fields[fields.length - 1]] = value;
}
function hydrateFilterState(inputState) {
  const state = structuredClone(inputState);
  for (const path of setContainsStatePaths) {
    const selected = path.split(".").reduce((value, field) => value?.[field], state);
    setStatePath(state, path, new Set(selected));
  }
  return state;
}
const hydratedFilterCases = input.filterCases.map(filterCase => ({
  ...filterCase,
  state: hydrateFilterState(filterCase.state)
}));
function idDigest(values) {
  const sorted = [...values].sort();
  return "sha256:" + crypto.createHash("sha256").update(JSON.stringify(sorted) + "\\n").digest("hex");
}
const filterResults = hydratedFilterCases.map(filterCase => {
  const ids = recordsByKind[filterCase.recordKind]
    .filter(record => explorerRecordEligibleForState(
      filterCase.recordKind,
      record,
      filterCase.state,
      conceptByViewId
    ))
    .map(record => record[idFieldByKind[filterCase.recordKind]]);
  return {
    id: filterCase.id,
    recordKind: filterCase.recordKind,
    count: ids.length,
    idDigest: idDigest(ids)
  };
});
const facetDefinitions = input.conceptFacetFields.map(field => [field, field]);
const documents = buildSearchDocuments(input.explorer.concepts, facetDefinitions);
const searchResults = input.searchCases.map(searchCase => {
  const ranked = rankSearchDocuments(documents, searchCase.query, searchCase.semanticRing);
  const index = ranked.findIndex(result =>
    result.document.concept.releaseId === searchCase.expectedReleaseId
      && result.document.concept.conceptId === searchCase.expectedConceptId
  );
  const observed = index >= 0 ? ranked[index] : null;
  return {
    id: searchCase.id,
    observedRank: observed ? index + 1 : null,
    observedScore: observed ? observed.score : null,
    observedMatch: observed ? observed.match : null
  };
});
const aggregateSearchResults = input.aggregateSearchCases.map(searchCase => {
  const ranked = rankSearchDocuments(documents, searchCase.query, searchCase.semanticRing);
  const ids = ranked.map(result => result.document.concept.viewId);
  const expectedRelease = ranked.every(result =>
    result.document.concept.releaseId === searchCase.expectedReleaseId
  );
  const oneMatch = ranked.length > 0
    && ranked.every(result => result.match === ranked[0].match);
  return {
    id: searchCase.id,
    observedResultCount: ranked.length,
    observedViewIdDigest: idDigest(ids),
    observedMatch: expectedRelease && oneMatch ? ranked[0].match : null
  };
});
const featureFields = {
  sourceIdentifier: "identifier",
  sourceFact: "sourceFacts",
  exactNotation: "notation",
  definitionOrScopeNote: "notes"
};
const searchFeatureCoverage = [];
for (const [feature, field] of Object.entries(featureFields)) {
  for (const ring of input.rings) {
    const ids = documents
      .filter(document => document.concept.semanticRing === ring && Boolean(document[field]))
      .map(document => document.concept.viewId);
    if (ids.length) searchFeatureCoverage.push({
      feature,
      semanticRing: ring,
      conceptCount: ids.length,
      viewIdDigest: idDigest(ids)
    });
  }
}
process.stdout.write(JSON.stringify({
  nodeVersion: process.version,
  setContainsStateRepresentation: hydratedFilterCases.every(filterCase =>
    setContainsStatePaths.every(path =>
      path.split(".").reduce((value, field) => value?.[field], filterCase.state) instanceof Set
    )
  ) ? "Set" : "other",
  filterResults,
  searchResults,
  aggregateSearchResults,
  searchFeatureCoverage
}));
""",
        )
    )
    input_payload = json.dumps(
        {
            "explorer": _plain(explorer),
            "filterCases": _plain(filter_cases),
            "searchCases": _plain(search_cases),
            "aggregateSearchCases": _plain(aggregate_search_cases),
            "conceptFacetFields": list(_CONCEPT_FACETS),
            "rings": list(_RINGS),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        completed = subprocess.run(
            ["node", "-e", script],
            input=input_payload,
            capture_output=True,
            check=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ExplorerAcceptanceError(
            "shipped explorer JavaScript did not execute successfully in Node"
        ) from error
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ExplorerAcceptanceError(
            "shipped explorer JavaScript returned invalid acceptance evidence"
        ) from error
    return cast(dict[str, Any], result)


def _planning_filter_selections(
    *,
    ring: str | None = None,
    source_module: str = "",
    resource_id: str = "",
    participation: str = "",
    disposition: str = "",
) -> dict[str, object]:
    return {
        "ring": set(_RINGS if ring is None else (ring,)),
        "sourceModule": source_module,
        "resourceId": resource_id,
        "participation": participation,
        "disposition": disposition,
    }


def _planning_filter_measurements(explorer: Mapping[str, Any]) -> dict[str, Any]:
    context = _mapping(explorer.get("releaseContext"), "explorer releaseContext")
    rows = tuple(
        _mapping(value, f"explorer releaseContext.planningRows[{index}]")
        for index, value in enumerate(
            _sequence(
                context.get("planningRows"),
                "explorer releaseContext.planningRows",
            )
        )
    )
    row_ids = [_iri(row.get("rowId"), "explorer planning row rowId") for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise ExplorerAcceptanceError("explorer planning rows repeat a rowId")
    facets = _mapping(explorer.get("facets"), "explorer facets")
    advertised = {
        "ring": list(_RINGS),
        "sourceModule": [
            _text(value, "explorer facets.sourceModules[]")
            for value in _sequence(
                facets.get("sourceModules"),
                "explorer facets.sourceModules",
            )
        ],
        "resourceId": [
            _text(value, "explorer facets.resourceIds[]")
            for value in _sequence(
                facets.get("resourceIds"),
                "explorer facets.resourceIds",
            )
        ],
        "participation": [
            _text(value, "explorer facets.participations[]")
            for value in _sequence(
                facets.get("participations"),
                "explorer facets.participations",
            )
        ],
        "disposition": [
            _text(value, "explorer facets.planningDispositions[]")
            for value in _sequence(
                facets.get("planningDispositions"),
                "explorer facets.planningDispositions",
            )
        ],
    }
    observed = {
        "ring": {cast(str, row["semanticRing"]) for row in rows},
        "sourceModule": {cast(str, row["sourceModule"]) for row in rows},
        "resourceId": {cast(str, row["resourceId"]) for row in rows},
        "participation": {
            cast(str, row["atlasParticipation"])
            for row in rows
            if "atlasParticipation" in row
        },
        "disposition": {cast(str, row["disposition"]) for row in rows},
    }
    for dimension, values in observed.items():
        if not values <= set(advertised[dimension]):
            raise ExplorerAcceptanceError(
                f"explorer planning {dimension} filter omits a row value"
            )
    individual: list[dict[str, Any]] = []
    for dimension in (
        "ring",
        "sourceModule",
        "resourceId",
        "participation",
        "disposition",
    ):
        values: list[dict[str, Any]] = []
        for value in advertised[dimension]:
            selections = _planning_filter_selections(
                ring=(value if dimension == "ring" else None),
                source_module=(value if dimension == "sourceModule" else ""),
                resource_id=(value if dimension == "resourceId" else ""),
                participation=(value if dimension == "participation" else ""),
                disposition=(value if dimension == "disposition" else ""),
            )
            matching = [
                cast(str, row["rowId"])
                for row in rows
                if planning_row_eligible(row, selections)
            ]
            values.append(
                {
                    "value": value,
                    "count": len(matching),
                    "rowIdDigest": _id_digest(matching),
                }
            )
        individual.append({"dimension": dimension, "values": values})

    selector_rows = {
        (
            cast(str, row["semanticRing"]),
            cast(str, row["sourceModule"]),
            cast(str, row["resourceId"]),
            cast(str, row.get("atlasParticipation", "")),
            cast(str, row["disposition"]),
        )
        for row in rows
    }
    combined_cases: list[dict[str, Any]] = []
    covered: set[str] = set()
    for ring, source_module, resource_id, participation, disposition in sorted(
        selector_rows
    ):
        selections = _planning_filter_selections(
            ring=ring,
            source_module=source_module,
            resource_id=resource_id,
            participation=participation,
            disposition=disposition,
        )
        matching = [
            cast(str, row["rowId"])
            for row in rows
            if planning_row_eligible(row, selections)
        ]
        if not matching:
            raise ExplorerAcceptanceError(
                "an exact planning-row selector cannot reach its source row"
            )
        covered.update(matching)
        combined_cases.append(
            {
                "selection": {
                    "ring": ring,
                    "sourceModule": source_module,
                    "resourceId": resource_id,
                    "participation": participation,
                    "disposition": disposition,
                },
                "count": len(matching),
                "rowIdDigest": _id_digest(matching),
            }
        )
    if covered != set(row_ids):
        raise ExplorerAcceptanceError(
            "combined planning filters do not reach every exact planning row"
        )
    return {
        "semantics": _plain(PLANNING_FILTER_SEMANTICS),
        "rowTotal": len(rows),
        "rowIdDigest": _id_digest(row_ids),
        "individual": individual,
        "combined": {
            "caseCount": len(combined_cases),
            "coveredRowCount": len(covered),
            "coveredRowIdDigest": _id_digest(list(covered)),
            "cases": combined_cases,
        },
    }


def _reachability(
    atlas: VocabularyAtlasAsset,
    explorer: Mapping[str, Any],
) -> dict[str, Any]:
    queries = VocabularyAtlasQueries(atlas)
    concept_rows = tuple(
        _mapping(value, f"explorer concepts[{index}]")
        for index, value in enumerate(_sequence(explorer.get("concepts"), "explorer concepts"))
    )
    native_rows = tuple(
        _mapping(value, f"explorer nativeRelations[{index}]")
        for index, value in enumerate(
            _sequence(explorer.get("nativeRelations"), "explorer nativeRelations")
        )
    )
    mapping_rows = tuple(
        _mapping(value, f"explorer mappingAssertions[{index}]")
        for index, value in enumerate(
            _sequence(explorer.get("mappingAssertions"), "explorer mappingAssertions")
        )
    )
    concept_by_view = {cast(str, row["viewId"]): row for row in concept_rows}
    concept_keys = {
        (cast(str, row["releaseId"]), cast(str, row["conceptId"]), cast(str, row["recordId"]))
        for row in concept_rows
    }
    expected_concepts = {
        (value.release_id, value.concept_id, value.record_id)
        for value in queries.concepts()
    }
    if len(concept_by_view) != len(concept_rows) or concept_keys != expected_concepts:
        raise ExplorerAcceptanceError("explorer concepts are not the complete query result")

    model_native_by_id = {cast(str, row["id"]): row for row in native_rows}
    model_native_filters: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    model_native_endpoints: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in native_rows:
        relation_id = cast(str, row["id"])
        model_native_filters[
            (
                cast(str, row["semanticRing"]),
                cast(str, row["releaseId"]),
                cast(str, row["predicate"]),
            )
        ].add(relation_id)
        for concept_field in ("subjectConcept", "objectConcept"):
            model_native_endpoints[
                (cast(str, row["releaseId"]), cast(str, row[concept_field]))
            ].add(relation_id)

    native_ids: list[str] = []
    for relation in queries.native_relations():
        relation_id = relation.relation_id
        row = model_native_by_id.get(relation_id)
        if row is None:
            raise ExplorerAcceptanceError("a native query assertion is absent from the explorer")
        subject = concept_by_view.get(cast(str, row["subjectViewId"]))
        object_concept = concept_by_view.get(cast(str, row["objectViewId"]))
        if (
            subject is None
            or object_concept is None
            or subject.get("conceptId") != relation.subject_concept
            or object_concept.get("conceptId") != relation.object_concept
            or relation_id
            not in model_native_filters[
                (relation.semantic_ring, relation.release_id, relation.predicate_iri)
            ]
            or any(
                relation_id
                not in model_native_endpoints[(relation.release_id, concept_id)]
                for concept_id in (relation.subject_concept, relation.object_concept)
            )
        ):
            raise ExplorerAcceptanceError("a native assertion is unreachable through its endpoints or filters")
        native_ids.append(relation_id)
    if len(model_native_by_id) != len(native_ids):
        raise ExplorerAcceptanceError("explorer contains a native assertion outside generic queries")

    model_mapping_by_id = {cast(str, row["id"]): row for row in mapping_rows}
    model_mapping_filters: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    model_mapping_endpoints: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in mapping_rows:
        mapping_id = cast(str, row["id"])
        for evidence_class in cast(Sequence[str], row["evidenceClasses"]):
            model_mapping_filters[
                (
                    cast(str, row["semanticRing"]),
                    cast(str, row["relation"]),
                    evidence_class,
                )
            ].add(mapping_id)
        for release_field, concept_field in (
            ("sourceRelease", "sourceConcept"),
            ("targetRelease", "targetConcept"),
        ):
            model_mapping_endpoints[
                (cast(str, row[release_field]), cast(str, row[concept_field]))
            ].add(mapping_id)

    mapping_ids: list[str] = []
    for view in queries.mapping_assertions():
        assertion = view.assertion
        mapping_id = view.mapping_id
        row = model_mapping_by_id.get(mapping_id)
        expected_classes = {
            evidence.assertion.evidence_class for evidence in view.evidence_assertions
        }
        if row is None or set(cast(Sequence[str], row["evidenceClasses"])) != expected_classes:
            raise ExplorerAcceptanceError("a mapping query assertion or evidence class is absent")
        source = concept_by_view.get(cast(str, row["sourceViewId"]))
        target = concept_by_view.get(cast(str, row["targetViewId"]))
        if (
            source is None
            or target is None
            or source.get("conceptId") != assertion.source_concept
            or target.get("conceptId") != assertion.target_concept
            or any(
                mapping_id
                not in model_mapping_filters[
                    (assertion.semantic_ring, assertion.relation, evidence_class)
                ]
                for evidence_class in expected_classes
            )
            or any(
                mapping_id not in model_mapping_endpoints[endpoint]
                for endpoint in (
                    (assertion.source_release, assertion.source_concept),
                    (assertion.target_release, assertion.target_concept),
                )
            )
        ):
            raise ExplorerAcceptanceError("a mapping assertion is unreachable through its endpoints or filters")
        mapping_ids.append(mapping_id)
    if len(model_mapping_by_id) != len(mapping_ids):
        raise ExplorerAcceptanceError("explorer contains a mapping assertion outside generic queries")

    return {
        "concepts": {
            "total": len(concept_keys),
            "keyDigest": _id_digest(["\u001f".join(value) for value in concept_keys]),
        },
        "nativeRelations": {
            "total": len(native_ids),
            "endpointChecks": len(native_ids) * 2,
            "filterChecks": len(native_ids),
            "idDigest": _id_digest(native_ids),
        },
        "mappingAssertions": {
            "total": len(mapping_ids),
            "endpointChecks": len(mapping_ids) * 2,
            "filterChecks": sum(
                len(cast(Sequence[str], row["evidenceClasses"]))
                for row in mapping_rows
            ),
            "idDigest": _id_digest(mapping_ids),
        },
    }


def _normalize_corpus(
    corpus: Mapping[str, Any],
    *,
    release_ids: Sequence[str],
) -> dict[str, Any]:
    _exact_fields(corpus, _CORPUS_FIELDS, "explorer search corpus")
    if corpus.get("type") != EXPLORER_SEARCH_CORPUS_TYPE:
        raise ExplorerAcceptanceError("explorer search corpus type is unsupported")
    if corpus.get("schemaVersion") != EXPLORER_SEARCH_CORPUS_VERSION:
        raise ExplorerAcceptanceError("explorer search corpus schemaVersion is unsupported")
    reviewed_at = _text(corpus.get("reviewedAt"), "explorer search corpus reviewedAt")
    try:
        reviewed_at = require_aware_datetime_text(reviewed_at, label="explorer search corpus reviewedAt")
    except SourceIdentityError as error:
        raise ExplorerAcceptanceError(str(error)) from error
    corpus_releases = [
        _iri(value, "explorer search corpus releaseIds[]")
        for value in _sequence(corpus.get("releaseIds"), "explorer search corpus releaseIds")
    ]
    if corpus_releases != sorted(set(release_ids)):
        raise ExplorerAcceptanceError("explorer search corpus does not pin every and only explorer release")
    cases: list[dict[str, Any]] = []
    for index, raw in enumerate(_sequence(corpus.get("cases"), "explorer search corpus cases")):
        label = f"explorer search corpus cases[{index}]"
        row = _mapping(raw, label)
        _exact_fields(row, _CASE_FIELDS, label)
        ring = row.get("semanticRing")
        category = row.get("category")
        if ring not in _RING_ORDER or category not in _SEARCH_CATEGORIES:
            raise ExplorerAcceptanceError(f"{label} ring or category is unsupported")
        maximum_rank = _count(row.get("maximumRank"), f"{label}.maximumRank", positive=True)
        expected_rank = (
            1 if category in {"exactIdentifier", "exactPreferredLabel"} else 5
        )
        if maximum_rank != expected_rank:
            raise ExplorerAcceptanceError(f"{label}.maximumRank must be {expected_rank}")
        cases.append(
            {
                "id": _iri(row.get("id"), f"{label}.id"),
                "semanticRing": cast(str, ring),
                "category": cast(str, category),
                "query": _text(row.get("query"), f"{label}.query"),
                "expectedReleaseId": _iri(
                    row.get("expectedReleaseId"),
                    f"{label}.expectedReleaseId",
                ),
                "expectedConceptId": _iri(
                    row.get("expectedConceptId"),
                    f"{label}.expectedConceptId",
                ),
                "maximumRank": maximum_rank,
            }
        )
    if len({row["id"] for row in cases}) != len(cases):
        raise ExplorerAcceptanceError("explorer search corpus repeats a case id")
    cases.sort(key=lambda row: cast(str, row["id"]))
    aggregate_cases: list[dict[str, Any]] = []
    for index, raw in enumerate(
        _sequence(
            corpus.get("aggregateCases"),
            "explorer search corpus aggregateCases",
        )
    ):
        label = f"explorer search corpus aggregateCases[{index}]"
        row = _mapping(raw, label)
        _exact_fields(row, _AGGREGATE_CASE_FIELDS, label)
        ring = row.get("semanticRing")
        if ring not in _RING_ORDER or row.get("category") != "sourceFact":
            raise ExplorerAcceptanceError(
                f"{label} ring or aggregate category is unsupported"
            )
        expected_match = _text(row.get("expectedMatch"), f"{label}.expectedMatch")
        if expected_match != "Source or release fact":
            raise ExplorerAcceptanceError(
                f"{label}.expectedMatch must execute the source-fact branch"
            )
        expected_digest = _text(
            row.get("expectedViewIdDigest"),
            f"{label}.expectedViewIdDigest",
        )
        if _SHA256.fullmatch(expected_digest) is None:
            raise ExplorerAcceptanceError(
                f"{label}.expectedViewIdDigest must be sha256:<64 lowercase hex>"
            )
        aggregate_cases.append(
            {
                "id": _iri(row.get("id"), f"{label}.id"),
                "semanticRing": cast(str, ring),
                "category": "sourceFact",
                "query": _text(row.get("query"), f"{label}.query"),
                "expectedReleaseId": _iri(
                    row.get("expectedReleaseId"),
                    f"{label}.expectedReleaseId",
                ),
                "expectedResultCount": _count(
                    row.get("expectedResultCount"),
                    f"{label}.expectedResultCount",
                    positive=True,
                ),
                "expectedViewIdDigest": expected_digest,
                "expectedMatch": expected_match,
            }
        )
    if not aggregate_cases:
        raise ExplorerAcceptanceError(
            "explorer search corpus requires a reviewed source-fact aggregate case"
        )
    all_case_ids = [
        *(cast(str, row["id"]) for row in cases),
        *(cast(str, row["id"]) for row in aggregate_cases),
    ]
    if len(all_case_ids) != len(set(all_case_ids)):
        raise ExplorerAcceptanceError("explorer search corpus repeats a case id")
    aggregate_cases.sort(key=lambda row: cast(str, row["id"]))
    return {
        "type": EXPLORER_SEARCH_CORPUS_TYPE,
        "schemaVersion": EXPLORER_SEARCH_CORPUS_VERSION,
        "reviewedBy": _iri(corpus.get("reviewedBy"), "explorer search corpus reviewedBy"),
        "reviewedAt": reviewed_at,
        "releaseIds": corpus_releases,
        "cases": cases,
        "aggregateCases": aggregate_cases,
    }


def _validate_case_meaning(case: Mapping[str, Any], concept: Mapping[str, Any]) -> None:
    category = cast(str, case["category"])
    query = cast(str, case["query"])
    concept_id = cast(str, concept["conceptId"])
    preferred = cast(str, concept["label"])
    labels = [
        cast(str, value)
        for value in cast(Sequence[str], concept.get("searchLabels", []))
    ]
    alternate_labels = [value for value in labels if value != preferred]
    normalized_query = _normalize_search(query)
    normalized_labels = [_normalize_search(value) for value in labels]
    if category == "exactIdentifier" and query != concept_id:
        raise ExplorerAcceptanceError("exactIdentifier search case does not use the exact concept identifier")
    if category == "exactPreferredLabel" and query != preferred:
        raise ExplorerAcceptanceError("exactPreferredLabel search case does not use the preferred label")
    if category == "exactNotation" and query != concept.get("notation"):
        raise ExplorerAcceptanceError(
            "exactNotation search case does not use the exact concept notation"
        )
    if category == "definitionOrScopeNote":
        notes = _normalize_search(
            " ".join(
                str(concept.get(field, ""))
                for field in ("definition", "scopeNote")
            )
        )
        if not normalized_query or not all(
            token in notes for token in normalized_query.split()
        ):
            raise ExplorerAcceptanceError(
                "definitionOrScopeNote search case is not supported by the concept notes"
            )
    alternate_forms = {_normalize_search(value) for value in alternate_labels}
    parenthetical_forms: set[str] = set()
    for value in labels:
        parenthetical = re.fullmatch(r"\s*(.*?)\s*\(([^()]+)\)\s*", value)
        if parenthetical is not None:
            parenthetical_forms.update(
                _normalize_search(part)
                for part in parenthetical.groups()
                if _normalize_search(part)
            )
    alias_forms = alternate_forms | parenthetical_forms
    recognized_forms = alternate_forms | parenthetical_forms
    if category == "alias" and normalized_query not in alias_forms:
        raise ExplorerAcceptanceError("alias search case is not a retained alias form")
    if category == "recognizedVariant" and normalized_query not in recognized_forms:
        raise ExplorerAcceptanceError(f"{category} search case is not a retained label form")
    if category == "normalizedPunctuationSpacing" and (
        normalized_query not in normalized_labels or query in labels
    ):
        raise ExplorerAcceptanceError("normalized punctuation search case does not exercise normalization")
    if category == "usefulPrefix" and not any(
        len(normalized_query) >= 3
        and normalized_query != value
        and value.startswith(normalized_query)
        for value in normalized_labels
    ):
        raise ExplorerAcceptanceError("usefulPrefix search case is not a useful retained-label prefix")
    typo_targets = [
        *normalized_labels,
        *(token for value in normalized_labels for token in value.split()),
    ]
    if category == "reviewedOneEditTypo" and min(
        (_edit_distance(normalized_query, value) for value in typo_targets),
        default=99,
    ) != 1:
        raise ExplorerAcceptanceError("reviewedOneEditTypo search case is not one edit from a retained label")


def _search_measurement(
    explorer: Mapping[str, Any],
    corpus: Mapping[str, Any],
    *,
    corpus_path: str,
    corpus_file_digest: str,
) -> dict[str, Any]:
    if _SHA256.fullmatch(corpus_file_digest) is None:
        raise ExplorerAcceptanceError(
            "explorer search corpus fileDigest must be sha256:<64 lowercase hex>"
        )
    releases = [
        cast(str, _mapping(value, "explorer release")["releaseId"])
        for value in _sequence(explorer.get("conceptReleases"), "explorer conceptReleases")
    ]
    normalized = _normalize_corpus(corpus, release_ids=releases)
    concepts = {
        (cast(str, row["releaseId"]), cast(str, row["conceptId"])): row
        for row in (
            _mapping(value, "explorer concept")
            for value in _sequence(explorer.get("concepts"), "explorer concepts")
        )
    }
    available_rings = [
        ring
        for ring in _RINGS
        if any(row["semanticRing"] == ring for row in concepts.values())
    ]
    coverage = {
        (cast(str, row["semanticRing"]), cast(str, row["category"]))
        for row in cast(Sequence[Mapping[str, Any]], normalized["cases"])
    }
    core_categories = {
        "exactIdentifier",
        "exactPreferredLabel",
        "alias",
        "recognizedVariant",
        "normalizedPunctuationSpacing",
        "usefulPrefix",
        "reviewedOneEditTypo",
    }
    feature_coverage = _search_feature_coverage(explorer)
    feature_rings = {
        (cast(str, row["semanticRing"]), cast(str, row["feature"]))
        for row in feature_coverage
    }
    required = {
        (ring, category)
        for ring in available_rings
        for category in core_categories
    }
    required.update(
        (ring, category)
        for ring in available_rings
        for category in ("exactNotation", "definitionOrScopeNote")
        if (ring, category) in feature_rings
    )
    if coverage != required:
        raise ExplorerAcceptanceError("reviewed search corpus does not cover every category in every available ring")

    results: list[dict[str, Any]] = []
    for case in cast(Sequence[Mapping[str, Any]], normalized["cases"]):
        key = (
            cast(str, case["expectedReleaseId"]),
            cast(str, case["expectedConceptId"]),
        )
        concept = concepts.get(key)
        if concept is None or concept.get("semanticRing") != case["semanticRing"]:
            raise ExplorerAcceptanceError("reviewed search case names an unavailable concept or ring")
        _validate_case_meaning(case, concept)
        ranked = rank_explorer_search(
            explorer,
            semantic_ring=cast(str, case["semanticRing"]),
            query=cast(str, case["query"]),
        )
        observed = next(
            (
                row
                for row in ranked
                if row["releaseId"] == key[0] and row["conceptId"] == key[1]
            ),
            None,
        )
        if observed is None or cast(int, observed["rank"]) > cast(int, case["maximumRank"]):
            raise ExplorerAcceptanceError(
                f"reviewed search case {case['id']} did not place its expected concept within rank {case['maximumRank']}"
            )
        required_branch = {
            "exactIdentifier": (920, "Exact identifier"),
            "exactNotation": (940, "Exact notation"),
            "definitionOrScopeNote": (420, "Definition or scope note"),
        }.get(cast(str, case["category"]))
        if required_branch is not None and (
            observed["score"],
            observed["match"],
        ) != required_branch:
            raise ExplorerAcceptanceError(
                f"reviewed search case {case['id']} did not execute its required search branch"
            )
        results.append(
            {
                **_plain(case),
                "observedRank": observed["rank"],
                "observedScore": observed["score"],
                "observedMatch": observed["match"],
            }
        )
    aggregate_results: list[dict[str, Any]] = []
    for case in cast(
        Sequence[Mapping[str, Any]],
        normalized["aggregateCases"],
    ):
        ranked = rank_explorer_search(
            explorer,
            semantic_ring=cast(str, case["semanticRing"]),
            query=cast(str, case["query"]),
        )
        identifiers = [cast(str, row["viewId"]) for row in ranked]
        observed_digest = _id_digest(identifiers)
        if (
            len(ranked) != case["expectedResultCount"]
            or observed_digest != case["expectedViewIdDigest"]
            or any(
                row["releaseId"] != case["expectedReleaseId"]
                or row["match"] != case["expectedMatch"]
                for row in ranked
            )
        ):
            raise ExplorerAcceptanceError(
                f"reviewed aggregate search case {case['id']} differs in count, IDs, release, or search branch"
            )
        aggregate_results.append(
            {
                **_plain(case),
                "observedResultCount": len(ranked),
                "observedViewIdDigest": observed_digest,
                "observedMatch": case["expectedMatch"],
            }
        )
    return {
        "status": "passed",
        "source": {
            "path": _text(corpus_path, "explorer search corpus path"),
            "fileDigest": corpus_file_digest,
        },
        "availableRings": available_rings,
        "requiredCategories": list(_SEARCH_CATEGORIES),
        "requiredCoverage": [
            {"semanticRing": ring, "category": category}
            for ring, category in sorted(required)
        ],
        "featureCoverage": feature_coverage,
        "reviewedCorpusDigest": sha256_digest(_canonical_bytes(normalized)),
        "caseCount": len(results) + len(aggregate_results),
        "rankedCaseCount": len(results),
        "aggregateCaseCount": len(aggregate_results),
        "cases": results,
        "aggregateCases": aggregate_results,
        "corpus": normalized,
    }


def _acceptance_basis(
    atlas: VocabularyAtlasAsset,
    explorer: Mapping[str, Any],
    *,
    explorer_html: bytes,
    release_mode: ExplorerAcceptanceMode,
    reviewed_corpus: Mapping[str, Any] | None,
    reviewed_corpus_path: str | None,
    reviewed_corpus_file_digest: str | None,
) -> dict[str, Any]:
    if not isinstance(atlas, VocabularyAtlasAsset):
        raise ExplorerAcceptanceError("explorer acceptance requires a canonical VocabularyAtlasAsset")
    try:
        atlas._require_verified()
    except VocabularyAtlasError as error:
        raise ExplorerAcceptanceError(str(error)) from error
    if release_mode not in {"publicV1", "baselineEvidenceRc"}:
        raise ExplorerAcceptanceError("explorer acceptance release mode is unsupported")
    if explorer.get("type") != EXPLORER_TYPE or explorer.get("schemaVersion") != EXPLORER_SCHEMA_VERSION:
        raise ExplorerAcceptanceError("explorer type or schemaVersion is unsupported")
    atlas_row = _mapping(explorer.get("atlas"), "explorer atlas")
    if (
        atlas_row.get("assetId") != atlas.manifest.get("id")
        or atlas_row.get("manifestDigest") != atlas.manifest_digest
        or atlas_row.get("distributionDigest") != atlas.output_digest
    ):
        raise ExplorerAcceptanceError("explorer names another canonical Atlas")
    summary = _mapping(explorer.get("summary"), "explorer summary")
    if summary.get("truncated") is not False:
        raise ExplorerAcceptanceError("explorer acceptance requires the complete explorer")
    facets = _facet_measurements(explorer)
    planning_filters = _planning_filter_measurements(explorer)
    reachability = _reachability(atlas, explorer)
    if not isinstance(explorer_html, bytes):
        raise ExplorerAcceptanceError("explorer acceptance requires exact shipped HTML bytes")
    expected_html = render_atlas_explorer(explorer).encode("utf-8")
    if explorer_html != expected_html:
        raise ExplorerAcceptanceError(
            "shipped explorer HTML does not reproduce from its exact explorer data"
        )
    try:
        html_text = explorer_html.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExplorerAcceptanceError(
            "shipped explorer HTML must be UTF-8"
        ) from error
    if release_mode == "publicV1":
        if (
            reviewed_corpus is None
            or reviewed_corpus_path is None
            or reviewed_corpus_file_digest is None
        ):
            raise ExplorerAcceptanceError("publicV1 requires a reviewed explorer search corpus")
        search = _search_measurement(
            explorer,
            reviewed_corpus,
            corpus_path=reviewed_corpus_path,
            corpus_file_digest=reviewed_corpus_file_digest,
        )
        status = "passed"
    else:
        if any(
            value is not None
            for value in (
                reviewed_corpus,
                reviewed_corpus_path,
                reviewed_corpus_file_digest,
            )
        ):
            raise ExplorerAcceptanceError("baselineEvidenceRc uses the explicit public-corpus skip")
        available_rings = [
            ring
            for ring in _RINGS
            if any(
                _mapping(value, "explorer concept").get("semanticRing") == ring
                for value in _sequence(explorer.get("concepts"), "explorer concepts")
            )
        ]
        search = {
            "status": "skippedPublicOnly",
            "availableRings": available_rings,
            "requiredCategories": list(_SEARCH_CATEGORIES),
            "requiredCoverage": [],
            "featureCoverage": _search_feature_coverage(explorer),
            "caseCount": 0,
            "rankedCaseCount": 0,
            "aggregateCaseCount": 0,
            "cases": [],
            "aggregateCases": [],
        }
        status = "measuredBaselineOnly"
    filter_cases = _filter_cases(explorer)
    python_filter_results = _python_filter_results(explorer, filter_cases)
    javascript = _run_shipped_javascript(
        explorer,
        html_text=html_text,
        filter_cases=filter_cases,
        search_cases=cast(Sequence[Mapping[str, Any]], search["cases"]),
        aggregate_search_cases=cast(
            Sequence[Mapping[str, Any]],
            search["aggregateCases"],
        ),
    )
    if javascript.get("filterResults") != python_filter_results:
        raise ExplorerAcceptanceError(
            "shipped explorer filters differ between Python and JavaScript"
        )
    if javascript.get("setContainsStateRepresentation") != "Set":
        raise ExplorerAcceptanceError(
            "shipped explorer setContains filters did not execute with Set state"
        )
    python_search_results = [
        {
            "id": row["id"],
            "observedRank": row["observedRank"],
            "observedScore": row["observedScore"],
            "observedMatch": row["observedMatch"],
        }
        for row in cast(Sequence[Mapping[str, Any]], search["cases"])
    ]
    if javascript.get("searchResults") != python_search_results:
        raise ExplorerAcceptanceError(
            "shipped explorer search differs between Python and JavaScript"
        )
    python_aggregate_search_results = [
        {
            "id": row["id"],
            "observedResultCount": row["observedResultCount"],
            "observedViewIdDigest": row["observedViewIdDigest"],
            "observedMatch": row["observedMatch"],
        }
        for row in cast(
            Sequence[Mapping[str, Any]],
            search["aggregateCases"],
        )
    ]
    if (
        javascript.get("aggregateSearchResults")
        != python_aggregate_search_results
    ):
        raise ExplorerAcceptanceError(
            "shipped explorer aggregate search differs between Python and JavaScript"
        )
    if javascript.get("searchFeatureCoverage") != search["featureCoverage"]:
        raise ExplorerAcceptanceError(
            "shipped explorer search-document feature coverage differs between Python and JavaScript"
        )
    node_version = _text(
        javascript.get("nodeVersion"),
        "shipped explorer Node version",
    )
    filter_core = _extract_javascript_core(html_text, "explorer-filter-core")
    search_document_core = _extract_javascript_core(
        html_text,
        "explorer-search-document-core",
    )
    search_ranking_core = _extract_javascript_core(
        html_text,
        "explorer-search-ranking-core",
    )
    filter_results_by_id = {
        cast(str, row["id"]): row for row in python_filter_results
    }
    filter_execution = {
        "status": "passed",
        "semantics": _plain(EXPLORER_FILTER_SEMANTICS),
        "semanticsDigest": sha256_digest(
            _canonical_bytes(EXPLORER_FILTER_SEMANTICS)
        ),
        "coreDigest": sha256_digest(filter_core.encode("utf-8")),
        "nodeVersion": node_version,
        "setContainsStateRepresentation": "Set",
        "caseCount": len(filter_cases),
        "caseDigest": sha256_digest(_canonical_bytes(filter_cases)),
        "resultDigest": sha256_digest(_canonical_bytes(python_filter_results)),
        "cases": [
            {
                "id": case["id"],
                "recordKind": case["recordKind"],
                "dimension": case["dimension"],
                "value": case["value"],
                "count": filter_results_by_id[cast(str, case["id"])]["count"],
                "idDigest": filter_results_by_id[cast(str, case["id"])][
                    "idDigest"
                ],
            }
            for case in filter_cases
        ],
    }
    search["javascript"] = {
        "status": "passed",
        "nodeVersion": node_version,
        "documentCoreDigest": sha256_digest(
            search_document_core.encode("utf-8")
        ),
        "rankingCoreDigest": sha256_digest(search_ranking_core.encode("utf-8")),
        "resultDigest": sha256_digest(
            _canonical_bytes(
                {
                    "rankedCases": python_search_results,
                    "aggregateCases": python_aggregate_search_results,
                }
            )
        ),
        "featureCoverageDigest": sha256_digest(
            _canonical_bytes(search["featureCoverage"])
        ),
    }
    explorer_payload = _canonical_bytes(explorer)
    return {
        "type": EXPLORER_ACCEPTANCE_TYPE,
        "schemaVersion": EXPLORER_ACCEPTANCE_VERSION,
        "releaseMode": release_mode,
        "status": status,
        "atlas": {
            "id": atlas.manifest["id"],
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
        },
        "explorer": {
            "type": EXPLORER_TYPE,
            "schemaVersion": EXPLORER_SCHEMA_VERSION,
            "fileDigest": sha256_digest(explorer_payload),
            "byteLength": len(explorer_payload),
            "htmlFileDigest": sha256_digest(explorer_html),
            "htmlByteLength": len(explorer_html),
        },
        "facetMeasurements": facets,
        "filterExecution": filter_execution,
        "planningFilters": planning_filters,
        "reachability": reachability,
        "search": search,
    }


def _seal(basis: Mapping[str, Any]) -> dict[str, Any]:
    digest = sha256_digest(_canonical_bytes(basis))
    return {
        **_plain(basis),
        "id": _ACCEPTANCE_ID_PREFIX + digest.removeprefix("sha256:"),
        "recordDigest": digest,
    }


@dataclass(frozen=True, slots=True)
class VocabularyAtlasExplorerAcceptance:
    """One immutable explorer gate result derived from exact release inputs."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        row = _mapping(self.record, "explorer acceptance")
        if row.get("type") != EXPLORER_ACCEPTANCE_TYPE:
            raise ExplorerAcceptanceError("explorer acceptance type is unsupported")
        if row.get("schemaVersion") != EXPLORER_ACCEPTANCE_VERSION:
            raise ExplorerAcceptanceError("explorer acceptance schemaVersion is unsupported")
        if "id" not in row or "recordDigest" not in row:
            raise ExplorerAcceptanceError("explorer acceptance identity is incomplete")
        basis = {key: _plain(value) for key, value in row.items() if key not in {"id", "recordDigest"}}
        if _plain(row) != _seal(basis):
            raise ExplorerAcceptanceError("explorer acceptance identity or content digest differs")
        object.__setattr__(self, "record", cast(Mapping[str, Any], deep_freeze_json(row)))

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> Self:
        return cls(record=value)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise ExplorerAcceptanceError(f"explorer acceptance destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.artifact_bytes())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    def validate_inputs(
        self,
        atlas: VocabularyAtlasAsset,
        explorer: Mapping[str, Any],
        *,
        explorer_html: bytes,
    ) -> None:
        search = _mapping(self.record.get("search"), "explorer acceptance search")
        corpus_value = search.get("corpus")
        corpus = cast(Mapping[str, Any], corpus_value) if isinstance(corpus_value, Mapping) else None
        source_value = search.get("source")
        source = _mapping(source_value, "explorer acceptance search source") if source_value is not None else None
        expected = build_vocabulary_atlas_explorer_acceptance(
            atlas,
            explorer,
            explorer_html=explorer_html,
            release_mode=cast(ExplorerAcceptanceMode, self.record["releaseMode"]),
            reviewed_corpus=corpus,
            reviewed_corpus_path=(cast(str, source["path"]) if source is not None else None),
            reviewed_corpus_file_digest=(
                cast(str, source["fileDigest"]) if source is not None else None
            ),
        )
        if expected.as_record() != self.as_record():
            raise ExplorerAcceptanceError("explorer acceptance differs from its exact inputs")


def build_vocabulary_atlas_explorer_acceptance(
    atlas: VocabularyAtlasAsset,
    explorer: Mapping[str, Any],
    *,
    explorer_html: bytes,
    release_mode: ExplorerAcceptanceMode,
    reviewed_corpus: Mapping[str, Any] | None = None,
    reviewed_corpus_path: str | None = None,
    reviewed_corpus_file_digest: str | None = None,
) -> VocabularyAtlasExplorerAcceptance:
    """Execute and seal the complete explorer acceptance gate."""

    basis = _acceptance_basis(
        atlas,
        explorer,
        explorer_html=explorer_html,
        release_mode=release_mode,
        reviewed_corpus=reviewed_corpus,
        reviewed_corpus_path=reviewed_corpus_path,
        reviewed_corpus_file_digest=reviewed_corpus_file_digest,
    )
    return VocabularyAtlasExplorerAcceptance(_seal(basis))


def read_vocabulary_atlas_explorer_acceptance(
    path: Path | str,
    *,
    expected_file_digest: str,
) -> VocabularyAtlasExplorerAcceptance:
    """Open canonical explorer acceptance bytes under an external digest."""

    if not isinstance(expected_file_digest, str) or _SHA256.fullmatch(expected_file_digest) is None:
        raise ExplorerAcceptanceError("explorer acceptance expected file digest is invalid")
    source = Path(path)
    if source.is_symlink():
        raise ExplorerAcceptanceError("explorer acceptance path must not be a symlink")
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise ExplorerAcceptanceError("explorer acceptance file is unavailable") from error
    if sha256_digest(payload) != expected_file_digest:
        raise ExplorerAcceptanceError("explorer acceptance file digest differs")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ExplorerAcceptanceError("explorer acceptance must be valid canonical UTF-8 JSON") from error
    if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
        raise ExplorerAcceptanceError("explorer acceptance bytes are not canonical")
    return VocabularyAtlasExplorerAcceptance.from_record(value)


__all__ = [
    "EXPLORER_ACCEPTANCE_TYPE",
    "EXPLORER_ACCEPTANCE_VERSION",
    "EXPLORER_SEARCH_CORPUS_TYPE",
    "EXPLORER_SEARCH_CORPUS_VERSION",
    "ExplorerAcceptanceError",
    "VocabularyAtlasExplorerAcceptance",
    "build_vocabulary_atlas_explorer_acceptance",
    "planning_row_eligible",
    "rank_explorer_search",
    "read_vocabulary_atlas_explorer_acceptance",
]

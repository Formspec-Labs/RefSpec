"""Content-derived receipts for bounded source-concept selections.

``SelectionReceipt`` records why a verified subset or policy frontier contains
exactly its selected concepts.  It is deliberately non-authorizing: the
receipt proves build inputs, selection policy, coverage, and hierarchy-boundary
handling, but it grants neither atlas participation nor product use.

The selected side is present in full.  The caller supplies the complementary
source observation identifiers and the source ``broader`` edges during every
verification; the receipt pins those closed sets by digest.  This prevents a
truncated receipt from silently redefining its own verification universe.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
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

from .concept_release import ConceptReleaseError, normalize_concept_release_pin

SELECTION_RECEIPT_TYPE = "AtlasSelectionReceipt"
SELECTION_RECEIPT_VERSION = "1.0"

SelectionScopeKind = Literal["verifiedSubset", "policyFrontier"]
SelectionReasonKind = Literal[
    "predicateMatch",
    "publisherMappingEndpoint",
    "hierarchyContext",
]
BroaderEdgeDisposition = Literal["included", "externalReference", "omitted"]

_SCOPE_KINDS = frozenset({"verifiedSubset", "policyFrontier"})
_REASON_KINDS = frozenset(
    {
        "predicateMatch",
        "publisherMappingEndpoint",
        "hierarchyContext",
    }
)
_EDGE_DISPOSITIONS = frozenset({"included", "externalReference", "omitted"})
_REFERENCE_PARTICIPATION = frozenset({"core", "specialist"})
_DISTRIBUTION_COVERAGE = frozenset({"complete", "partial"})
_COVERAGE_STATUS = frozenset({"pass", "gap"})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

_SOURCE_CAPTURE_FIELDS = frozenset(
    {
        "role",
        "resourceManifest",
        "logicalDigest",
        "bundleManifestDigest",
        "observationSetDigest",
        "coverageReportDigest",
        "distributionCoverage",
        "coverageStatus",
        "sourceObservedCount",
        "parsedObservationCount",
        "packagedObservationCount",
        "excludedObservationCount",
        "failedObservationCount",
        "gapCount",
    }
)
_REFERENCE_INPUT_FIELDS = frozenset({"release", "atlasIndex", "participationRow"})
_ATLAS_INDEX_PIN_FIELDS = frozenset({"role", "id", "indexDigest", "fileDigest"})
_PARTICIPATION_ROW_FIELDS = frozenset(
    {
        "rowId",
        "rowDigest",
        "releaseId",
        "atlasParticipation",
    }
)
_POLICY_FIELDS = frozenset({"id", "version", "selectors", "hierarchyDepth", "compilerDigest"})
_SELECTOR_FIELDS = frozenset({"id", "version", "parameters"})
_SELECTED_CONCEPT_FIELDS = frozenset({"conceptId", "sourceObservationId", "reasons"})
_SOURCE_BROADER_EDGE_FIELDS = frozenset({"narrowerConcept", "broaderConcept"})
_EDGE_DISPOSITION_FIELDS = frozenset({"narrowerConcept", "broaderConcept", "disposition", "reason"})
_COUNTS_FIELDS = frozenset(
    {
        "selectedConcepts",
        "unselectedObservations",
        "broaderEdges",
        "includedBroaderEdges",
        "externalReferenceBroaderEdges",
        "omittedBroaderEdges",
    }
)
_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "scopeKind",
        "sourceCapture",
        "referenceInputs",
        "selectionPolicy",
        "counts",
        "selectedConcepts",
        "broaderEdgeDispositions",
        "sourceBroaderEdgesDigest",
        "unselectedObservationIdsDigest",
    }
)
_RECORD_FIELDS = _BASIS_FIELDS | {"id", "contentDigest"}


class SelectionReceiptError(ValueError):
    """A selection receipt is incomplete, mutable, or inconsistent."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise SelectionReceiptError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SelectionReceiptError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SelectionReceiptError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise SelectionReceiptError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SelectionReceiptError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise SelectionReceiptError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise SelectionReceiptError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SelectionReceiptError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_count(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SelectionReceiptError(f"{label} must be a non-negative integer")
    if value > binding.SAFE_INTEGER:
        raise SelectionReceiptError(f"{label} exceeds the interoperable JSON range")
    return value


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SelectionReceiptError(f"{label} must be valid canonical UTF-8 JSON") from error


def _normalized_source_capture(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "selection receipt sourceCapture")
    _require_exact_fields(row, _SOURCE_CAPTURE_FIELDS, "selection receipt sourceCapture")
    if row.get("role") != "SourceControlledResourceCapture":
        raise SelectionReceiptError("selection receipt sourceCapture.role must be SourceControlledResourceCapture")
    distribution = row.get("distributionCoverage")
    if not isinstance(distribution, str) or distribution not in _DISTRIBUTION_COVERAGE:
        raise SelectionReceiptError("selection receipt sourceCapture.distributionCoverage must be complete or partial")
    status = row.get("coverageStatus")
    if not isinstance(status, str) or status not in _COVERAGE_STATUS:
        raise SelectionReceiptError("selection receipt sourceCapture.coverageStatus must be pass or gap")
    source_observed = _require_count(
        row.get("sourceObservedCount"),
        "selection receipt sourceCapture.sourceObservedCount",
    )
    parsed = _require_count(
        row.get("parsedObservationCount"),
        "selection receipt sourceCapture.parsedObservationCount",
    )
    packaged = _require_count(
        row.get("packagedObservationCount"),
        "selection receipt sourceCapture.packagedObservationCount",
    )
    excluded = _require_count(
        row.get("excludedObservationCount"),
        "selection receipt sourceCapture.excludedObservationCount",
    )
    failed = _require_count(
        row.get("failedObservationCount"),
        "selection receipt sourceCapture.failedObservationCount",
    )
    gaps = _require_count(
        row.get("gapCount"),
        "selection receipt sourceCapture.gapCount",
    )
    if parsed != packaged:
        raise SelectionReceiptError("selection receipt source capture must package every parsed observation")
    if source_observed != parsed + excluded + failed:
        raise SelectionReceiptError("selection receipt source capture does not account for every observed record")
    has_gap = excluded > 0 or failed > 0 or gaps > 0
    if (status == "pass" and has_gap) or (status == "gap" and not has_gap):
        raise SelectionReceiptError("selection receipt source capture coverageStatus disagrees with its gaps")
    return {
        "role": "SourceControlledResourceCapture",
        "resourceManifest": _require_iri(
            row.get("resourceManifest"),
            "selection receipt sourceCapture.resourceManifest",
        ),
        "logicalDigest": _require_digest(
            row.get("logicalDigest"),
            "selection receipt sourceCapture.logicalDigest",
        ),
        "bundleManifestDigest": _require_digest(
            row.get("bundleManifestDigest"),
            "selection receipt sourceCapture.bundleManifestDigest",
        ),
        "observationSetDigest": _require_digest(
            row.get("observationSetDigest"),
            "selection receipt sourceCapture.observationSetDigest",
        ),
        "coverageReportDigest": _require_digest(
            row.get("coverageReportDigest"),
            "selection receipt sourceCapture.coverageReportDigest",
        ),
        "distributionCoverage": distribution,
        "coverageStatus": status,
        "sourceObservedCount": source_observed,
        "parsedObservationCount": parsed,
        "packagedObservationCount": packaged,
        "excludedObservationCount": excluded,
        "failedObservationCount": failed,
        "gapCount": gaps,
    }


def _normalized_reference_inputs(value: object) -> tuple[dict[str, Any], ...]:
    rows = _require_array(value, "selection receipt referenceInputs")
    result: list[dict[str, Any]] = []
    release_ids: set[str] = set()
    row_ids: set[str] = set()
    common_atlas_index: dict[str, str] | None = None
    for index, value_row in enumerate(rows):
        label = f"selection receipt referenceInputs[{index}]"
        row = _require_mapping(value_row, label)
        _require_exact_fields(row, _REFERENCE_INPUT_FIELDS, label)
        try:
            release = normalize_concept_release_pin(row.get("release"))
        except ConceptReleaseError as error:
            raise SelectionReceiptError(f"{label}.release: {error}") from error
        if release["semanticRing"] != "subject":
            raise SelectionReceiptError(f"{label}.release.semanticRing must be subject")
        release_id = cast(str, release["releaseId"])
        if release_id in release_ids:
            raise SelectionReceiptError("selection receipt repeats a reference release")
        release_ids.add(release_id)

        atlas_index = _require_mapping(row.get("atlasIndex"), f"{label}.atlasIndex")
        _require_exact_fields(
            atlas_index,
            _ATLAS_INDEX_PIN_FIELDS,
            f"{label}.atlasIndex",
        )
        if atlas_index.get("role") != "AtlasIndex":
            raise SelectionReceiptError(f"{label}.atlasIndex.role must be AtlasIndex")
        normalized_atlas_index = {
            "role": "AtlasIndex",
            "id": _require_iri(atlas_index.get("id"), f"{label}.atlasIndex.id"),
            "indexDigest": _require_digest(
                atlas_index.get("indexDigest"),
                f"{label}.atlasIndex.indexDigest",
            ),
            "fileDigest": _require_digest(
                atlas_index.get("fileDigest"),
                f"{label}.atlasIndex.fileDigest",
            ),
        }
        if common_atlas_index is None:
            common_atlas_index = normalized_atlas_index
        elif common_atlas_index != normalized_atlas_index:
            raise SelectionReceiptError("selection receipt reference participation rows must use one exact atlas index")

        participation = _require_mapping(
            row.get("participationRow"),
            f"{label}.participationRow",
        )
        _require_exact_fields(
            participation,
            _PARTICIPATION_ROW_FIELDS,
            f"{label}.participationRow",
        )
        row_id = _require_iri(
            participation.get("rowId"),
            f"{label}.participationRow.rowId",
        )
        if row_id in row_ids:
            raise SelectionReceiptError("selection receipt repeats a participation row")
        row_ids.add(row_id)
        if participation.get("releaseId") != release_id:
            raise SelectionReceiptError(f"{label}.participationRow.releaseId differs from its reference release")
        participation_class = participation.get("atlasParticipation")
        if not isinstance(participation_class, str) or participation_class not in _REFERENCE_PARTICIPATION:
            raise SelectionReceiptError(f"{label}.participationRow.atlasParticipation must be core or specialist")
        result.append(
            {
                "release": release,
                "atlasIndex": normalized_atlas_index,
                "participationRow": {
                    "rowId": row_id,
                    "rowDigest": _require_digest(
                        participation.get("rowDigest"),
                        f"{label}.participationRow.rowDigest",
                    ),
                    "releaseId": release_id,
                    "atlasParticipation": participation_class,
                },
            }
        )
    result.sort(
        key=lambda item: (
            str(item["release"]["releaseId"]),
            str(item["participationRow"]["rowId"]),
        )
    )
    return tuple(result)


def _normalized_policy(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "selection receipt selectionPolicy")
    _require_exact_fields(row, _POLICY_FIELDS, "selection receipt selectionPolicy")
    raw_selectors = _require_array(
        row.get("selectors"),
        "selection receipt selectionPolicy.selectors",
    )
    if not raw_selectors:
        raise SelectionReceiptError("selection receipt selectionPolicy.selectors must not be empty")
    selectors: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw_selector in enumerate(raw_selectors):
        label = f"selection receipt selectionPolicy.selectors[{index}]"
        selector = _require_mapping(raw_selector, label)
        _require_exact_fields(selector, _SELECTOR_FIELDS, label)
        identifier = _require_iri(selector.get("id"), f"{label}.id")
        if identifier in identifiers:
            raise SelectionReceiptError("selection receipt selection policy repeats a selector id")
        identifiers.add(identifier)
        parameters = _plain(_require_mapping(selector.get("parameters"), f"{label}.parameters"))
        try:
            binding.validate_canonical_value(parameters)
        except (TypeError, ValueError) as error:
            raise SelectionReceiptError(f"{label}.parameters: {error}") from error
        selectors.append(
            {
                "id": identifier,
                "version": _require_text(selector.get("version"), f"{label}.version"),
                "parameters": parameters,
            }
        )
    selectors.sort(key=lambda item: (str(item["id"]), str(item["version"])))
    return {
        "id": _require_iri(row.get("id"), "selection receipt selectionPolicy.id"),
        "version": _require_text(
            row.get("version"),
            "selection receipt selectionPolicy.version",
        ),
        "selectors": selectors,
        "hierarchyDepth": _require_count(
            row.get("hierarchyDepth"),
            "selection receipt selectionPolicy.hierarchyDepth",
        ),
        "compilerDigest": _require_digest(
            row.get("compilerDigest"),
            "selection receipt selectionPolicy.compilerDigest",
        ),
    }


def _normalized_reason(
    value: object,
    *,
    label: str,
    selector_ids: frozenset[str],
    reference_release_ids: frozenset[str],
    hierarchy_depth: int,
) -> dict[str, Any]:
    row = _require_mapping(value, label)
    kind = row.get("kind")
    if not isinstance(kind, str) or kind not in _REASON_KINDS:
        raise SelectionReceiptError(f"{label}.kind is unsupported")
    if kind == "predicateMatch":
        _require_exact_fields(
            row,
            frozenset({"kind", "selector", "referenceRelease", "referenceConcept"}),
            label,
        )
        selector = _require_iri(row.get("selector"), f"{label}.selector")
        if selector not in selector_ids:
            raise SelectionReceiptError(f"{label}.selector is absent from the pinned selection policy")
        reference_release = _require_iri(
            row.get("referenceRelease"),
            f"{label}.referenceRelease",
        )
        if reference_release not in reference_release_ids:
            raise SelectionReceiptError(f"{label}.referenceRelease is absent from the exact reference inputs")
        return {
            "kind": kind,
            "selector": selector,
            "referenceRelease": reference_release,
            "referenceConcept": _require_iri(
                row.get("referenceConcept"),
                f"{label}.referenceConcept",
            ),
        }
    if kind == "publisherMappingEndpoint":
        _require_exact_fields(row, frozenset({"kind", "mapping"}), label)
        return {
            "kind": kind,
            "mapping": _require_iri(row.get("mapping"), f"{label}.mapping"),
        }
    _require_exact_fields(
        row,
        frozenset({"kind", "seedConcept", "depth"}),
        label,
    )
    depth = _require_count(row.get("depth"), f"{label}.depth")
    if depth < 1 or depth > hierarchy_depth:
        raise SelectionReceiptError(f"{label}.depth must be between 1 and selectionPolicy.hierarchyDepth")
    return {
        "kind": kind,
        "seedConcept": _require_iri(
            row.get("seedConcept"),
            f"{label}.seedConcept",
        ),
        "depth": depth,
    }


def _normalized_selected_concepts(
    value: object,
    *,
    policy: Mapping[str, Any],
    reference_inputs: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = _require_array(value, "selection receipt selectedConcepts")
    if not rows:
        raise SelectionReceiptError("selection receipt must select at least one concept")
    selector_ids = frozenset(
        cast(str, selector["id"]) for selector in cast(Sequence[Mapping[str, Any]], policy["selectors"])
    )
    hierarchy_depth = cast(int, policy["hierarchyDepth"])
    reference_release_ids = frozenset(cast(str, item["release"]["releaseId"]) for item in reference_inputs)
    result: list[dict[str, Any]] = []
    concept_ids: set[str] = set()
    observation_ids: set[str] = set()
    for index, raw_concept in enumerate(rows):
        label = f"selection receipt selectedConcepts[{index}]"
        concept = _require_mapping(raw_concept, label)
        _require_exact_fields(concept, _SELECTED_CONCEPT_FIELDS, label)
        concept_id = _require_iri(concept.get("conceptId"), f"{label}.conceptId")
        observation_id = _require_iri(
            concept.get("sourceObservationId"),
            f"{label}.sourceObservationId",
        )
        if concept_id in concept_ids:
            raise SelectionReceiptError("selection receipt repeats a selected concept")
        if observation_id in observation_ids:
            raise SelectionReceiptError("selection receipt maps more than one selected concept to a source observation")
        concept_ids.add(concept_id)
        observation_ids.add(observation_id)
        raw_reasons = _require_array(concept.get("reasons"), f"{label}.reasons")
        if not raw_reasons:
            raise SelectionReceiptError(f"{label}.reasons must not be empty")
        reasons = [
            _normalized_reason(
                reason,
                label=f"{label}.reasons[{reason_index}]",
                selector_ids=selector_ids,
                reference_release_ids=reference_release_ids,
                hierarchy_depth=hierarchy_depth,
            )
            for reason_index, reason in enumerate(raw_reasons)
        ]
        reasons.sort(key=lambda item: _canonical_bytes(item))
        if len({_canonical_bytes(item) for item in reasons}) != len(reasons):
            raise SelectionReceiptError(f"{label}.reasons must be unique")
        result.append(
            {
                "conceptId": concept_id,
                "sourceObservationId": observation_id,
                "reasons": reasons,
            }
        )
    for concept in result:
        for reason in cast(Sequence[Mapping[str, Any]], concept["reasons"]):
            if reason["kind"] == "hierarchyContext":
                seed = cast(str, reason["seedConcept"])
                if seed not in concept_ids or seed == concept["conceptId"]:
                    raise SelectionReceiptError("hierarchyContext seedConcept must name another selected concept")
    result.sort(key=lambda item: str(item["conceptId"]))
    return tuple(result)


def _normalized_iris(value: object, label: str) -> tuple[str, ...]:
    rows = _require_array(value, label)
    result = tuple(_require_iri(item, f"{label}[{index}]") for index, item in enumerate(rows))
    if len(set(result)) != len(result):
        raise SelectionReceiptError(f"{label} must contain unique identifiers")
    return tuple(sorted(result))


def _normalized_source_broader_edges(value: object) -> tuple[dict[str, str], ...]:
    rows = _require_array(value, "selection receipt source broader edges")
    result: list[dict[str, str]] = []
    pairs: set[tuple[str, str]] = set()
    for index, raw_edge in enumerate(rows):
        label = f"selection receipt source broader edges[{index}]"
        edge = _require_mapping(raw_edge, label)
        _require_exact_fields(edge, _SOURCE_BROADER_EDGE_FIELDS, label)
        narrower = _require_iri(edge.get("narrowerConcept"), f"{label}.narrowerConcept")
        broader = _require_iri(edge.get("broaderConcept"), f"{label}.broaderConcept")
        if narrower == broader:
            raise SelectionReceiptError(f"{label} cannot be reflexive")
        pair = (narrower, broader)
        if pair in pairs:
            raise SelectionReceiptError("selection receipt repeats a source broader edge")
        pairs.add(pair)
        result.append({"narrowerConcept": narrower, "broaderConcept": broader})
    result.sort(key=lambda item: (item["narrowerConcept"], item["broaderConcept"]))
    return tuple(result)


def _normalized_edge_dispositions(
    value: object,
    *,
    selected_concepts: Sequence[Mapping[str, Any]],
    source_broader_edges: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Any], ...]:
    rows = _require_array(value, "selection receipt broaderEdgeDispositions")
    selected_ids = frozenset(cast(str, item["conceptId"]) for item in selected_concepts)
    expected_pairs = {(edge["narrowerConcept"], edge["broaderConcept"]) for edge in source_broader_edges}
    result: list[dict[str, Any]] = []
    pairs: set[tuple[str, str]] = set()
    for index, raw_edge in enumerate(rows):
        label = f"selection receipt broaderEdgeDispositions[{index}]"
        edge = _require_mapping(raw_edge, label)
        _require_exact_fields(edge, _EDGE_DISPOSITION_FIELDS, label)
        narrower = _require_iri(edge.get("narrowerConcept"), f"{label}.narrowerConcept")
        broader = _require_iri(edge.get("broaderConcept"), f"{label}.broaderConcept")
        if narrower == broader:
            raise SelectionReceiptError(f"{label} cannot be reflexive")
        if narrower not in selected_ids:
            raise SelectionReceiptError(f"{label}.narrowerConcept must be a selected concept")
        disposition = edge.get("disposition")
        if not isinstance(disposition, str) or disposition not in _EDGE_DISPOSITIONS:
            raise SelectionReceiptError(f"{label}.disposition is unsupported")
        if disposition == "included" and broader not in selected_ids:
            raise SelectionReceiptError(f"{label} included broader concept must also be selected")
        if disposition != "included" and broader in selected_ids:
            raise SelectionReceiptError(f"{label} selected broader concept must use the included disposition")
        pair = (narrower, broader)
        if pair in pairs:
            raise SelectionReceiptError("selection receipt gives more than one disposition to a broader edge")
        pairs.add(pair)
        result.append(
            {
                "narrowerConcept": narrower,
                "broaderConcept": broader,
                "disposition": disposition,
                "reason": _require_text(edge.get("reason"), f"{label}.reason"),
            }
        )
    if pairs != expected_pairs:
        raise SelectionReceiptError("selection receipt broader-edge dispositions differ from the exact source edge set")
    if any(edge["narrowerConcept"] not in selected_ids for edge in source_broader_edges):
        raise SelectionReceiptError(
            "selection receipt source broader edges must be scoped to selected narrower concepts"
        )
    result.sort(key=lambda item: (item["narrowerConcept"], item["broaderConcept"]))
    return tuple(result)


def _counts(
    selected_concepts: Sequence[Mapping[str, Any]],
    unselected_observation_ids: Sequence[str],
    dispositions: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return {
        "selectedConcepts": len(selected_concepts),
        "unselectedObservations": len(unselected_observation_ids),
        "broaderEdges": len(dispositions),
        "includedBroaderEdges": sum(edge["disposition"] == "included" for edge in dispositions),
        "externalReferenceBroaderEdges": sum(edge["disposition"] == "externalReference" for edge in dispositions),
        "omittedBroaderEdges": sum(edge["disposition"] == "omitted" for edge in dispositions),
    }


def _selection_basis(
    *,
    scope_kind: SelectionScopeKind,
    source_capture: Mapping[str, Any],
    reference_inputs: Sequence[Mapping[str, Any]],
    selection_policy: Mapping[str, Any],
    selected_concepts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[Mapping[str, Any]],
    source_broader_edges: Sequence[Mapping[str, str]],
    unselected_observation_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "type": SELECTION_RECEIPT_TYPE,
        "schemaVersion": SELECTION_RECEIPT_VERSION,
        "scopeKind": scope_kind,
        "sourceCapture": _plain(source_capture),
        "referenceInputs": [_plain(value) for value in reference_inputs],
        "selectionPolicy": _plain(selection_policy),
        "counts": _counts(
            selected_concepts,
            unselected_observation_ids,
            dispositions,
        ),
        "selectedConcepts": [_plain(value) for value in selected_concepts],
        "broaderEdgeDispositions": [_plain(value) for value in dispositions],
        "sourceBroaderEdgesDigest": sha256_digest(_canonical_bytes([_plain(value) for value in source_broader_edges])),
        "unselectedObservationIdsDigest": sha256_digest(_canonical_bytes(list(unselected_observation_ids))),
    }


@dataclass(frozen=True, slots=True)
class SelectionReceipt:
    """An immutable, content-derived selection record with closed evidence sets."""

    record: Mapping[str, Any]
    _unselected_observation_ids: tuple[str, ...]
    _source_broader_edges: tuple[Mapping[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.record, Mapping):
            raise SelectionReceiptError("selection receipt must be an object")
        row = cast(dict[str, Any], _plain(self.record))
        _require_exact_fields(row, _RECORD_FIELDS, "selection receipt")
        if row.get("type") != SELECTION_RECEIPT_TYPE or row.get("schemaVersion") != SELECTION_RECEIPT_VERSION:
            raise SelectionReceiptError("selection receipt version is unsupported")
        scope_kind_raw = row.get("scopeKind")
        if not isinstance(scope_kind_raw, str) or scope_kind_raw not in _SCOPE_KINDS:
            raise SelectionReceiptError("selection receipt scopeKind must be verifiedSubset or policyFrontier")
        scope_kind = cast(SelectionScopeKind, scope_kind_raw)
        source_capture = _normalized_source_capture(row.get("sourceCapture"))
        reference_inputs = _normalized_reference_inputs(row.get("referenceInputs"))
        if scope_kind == "policyFrontier" and not reference_inputs:
            raise SelectionReceiptError("a policyFrontier selection receipt requires an exact reference release")
        policy = _normalized_policy(row.get("selectionPolicy"))
        selected = _normalized_selected_concepts(
            row.get("selectedConcepts"),
            policy=policy,
            reference_inputs=reference_inputs,
        )
        unselected = _normalized_iris(
            self._unselected_observation_ids,
            "selection receipt unselected observation ids",
        )
        selected_observations = {cast(str, concept["sourceObservationId"]) for concept in selected}
        if selected_observations & set(unselected):
            raise SelectionReceiptError("selected and unselected source observation identifiers overlap")
        if len(selected) + len(unselected) != cast(int, source_capture["packagedObservationCount"]):
            raise SelectionReceiptError("selection receipt does not account for every packaged source observation")
        source_edges = _normalized_source_broader_edges(self._source_broader_edges)
        dispositions = _normalized_edge_dispositions(
            row.get("broaderEdgeDispositions"),
            selected_concepts=selected,
            source_broader_edges=source_edges,
        )
        counts = _require_mapping(row.get("counts"), "selection receipt counts")
        _require_exact_fields(counts, _COUNTS_FIELDS, "selection receipt counts")
        expected_counts = _counts(selected, unselected, dispositions)
        for key, expected in expected_counts.items():
            if _require_count(counts.get(key), f"selection receipt counts.{key}") != expected:
                raise SelectionReceiptError(f"selection receipt counts.{key} differs from its records")
        basis = _selection_basis(
            scope_kind=scope_kind,
            source_capture=source_capture,
            reference_inputs=reference_inputs,
            selection_policy=policy,
            selected_concepts=selected,
            dispositions=dispositions,
            source_broader_edges=source_edges,
            unselected_observation_ids=unselected,
        )
        content_digest = sha256_digest(_canonical_bytes(basis))
        expected = {
            **basis,
            "id": ("urn:ref:atlas-selection-receipt:" + content_digest.removeprefix("sha256:")),
            "contentDigest": content_digest,
        }
        if row != expected:
            raise SelectionReceiptError("selection receipt content identity, evidence, or canonical order differs")
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(expected)),
        )
        object.__setattr__(self, "_unselected_observation_ids", unselected)
        object.__setattr__(
            self,
            "_source_broader_edges",
            tuple(cast(Mapping[str, str], deep_freeze_json(edge)) for edge in source_edges),
        )

    @classmethod
    def create(
        cls,
        *,
        scope_kind: SelectionScopeKind,
        source_capture: Mapping[str, Any],
        reference_inputs: Sequence[Mapping[str, Any]] = (),
        selection_policy: Mapping[str, Any],
        selected_concepts: Sequence[Mapping[str, Any]],
        broader_edge_dispositions: Sequence[Mapping[str, Any]],
        source_broader_edges: Sequence[Mapping[str, str]],
        unselected_observation_ids: Sequence[str],
    ) -> Self:
        if not isinstance(scope_kind, str) or scope_kind not in _SCOPE_KINDS:
            raise SelectionReceiptError("selection receipt scopeKind must be verifiedSubset or policyFrontier")
        normalized_scope = cast(SelectionScopeKind, scope_kind)
        source = _normalized_source_capture(source_capture)
        references = _normalized_reference_inputs(reference_inputs)
        if normalized_scope == "policyFrontier" and not references:
            raise SelectionReceiptError("a policyFrontier selection receipt requires an exact reference release")
        policy = _normalized_policy(selection_policy)
        selected = _normalized_selected_concepts(
            selected_concepts,
            policy=policy,
            reference_inputs=references,
        )
        unselected = _normalized_iris(
            unselected_observation_ids,
            "selection receipt unselected observation ids",
        )
        selected_observations = {cast(str, concept["sourceObservationId"]) for concept in selected}
        if selected_observations & set(unselected):
            raise SelectionReceiptError("selected and unselected source observation identifiers overlap")
        if len(selected) + len(unselected) != cast(int, source["packagedObservationCount"]):
            raise SelectionReceiptError("selection receipt does not account for every packaged source observation")
        source_edges = _normalized_source_broader_edges(source_broader_edges)
        dispositions = _normalized_edge_dispositions(
            broader_edge_dispositions,
            selected_concepts=selected,
            source_broader_edges=source_edges,
        )
        basis = _selection_basis(
            scope_kind=normalized_scope,
            source_capture=source,
            reference_inputs=references,
            selection_policy=policy,
            selected_concepts=selected,
            dispositions=dispositions,
            source_broader_edges=source_edges,
            unselected_observation_ids=unselected,
        )
        content_digest = sha256_digest(_canonical_bytes(basis))
        record = {
            **basis,
            "id": ("urn:ref:atlas-selection-receipt:" + content_digest.removeprefix("sha256:")),
            "contentDigest": content_digest,
        }
        return cls(
            record=record,
            _unselected_observation_ids=unselected,
            _source_broader_edges=source_edges,
        )

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        source_broader_edges: Sequence[Mapping[str, str]],
        unselected_observation_ids: Sequence[str],
    ) -> Self:
        return cls(
            record=record,
            _unselected_observation_ids=tuple(unselected_observation_ids),
            _source_broader_edges=tuple(source_broader_edges),
        )

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def content_digest(self) -> str:
        return cast(str, self.record["contentDigest"])

    @property
    def scope_kind(self) -> SelectionScopeKind:
        return cast(SelectionScopeKind, self.record["scopeKind"])

    @property
    def unselected_observation_ids(self) -> tuple[str, ...]:
        return self._unselected_observation_ids

    @property
    def source_broader_edges(self) -> tuple[Mapping[str, str], ...]:
        return self._source_broader_edges

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def verify(self) -> None:
        SelectionReceipt.from_record(
            self.as_record(),
            source_broader_edges=self._source_broader_edges,
            unselected_observation_ids=self._unselected_observation_ids,
        )

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise SelectionReceiptError(f"selection receipt destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}-",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.artifact_bytes())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination


@dataclass(frozen=True, slots=True)
class PinnedSelectionReceipt:
    """One exact receipt file plus the evidence sets needed to verify it."""

    path: Path
    file_digest: str
    receipt_id: str
    content_digest: str
    scope_kind: SelectionScopeKind
    _receipt: SelectionReceipt

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        source_broader_edges: Sequence[Mapping[str, str]],
        unselected_observation_ids: Sequence[str],
    ) -> Self:
        digest = _require_digest(
            expected_file_digest,
            "selection receipt file digest",
        )
        candidate = Path(path)
        if candidate.is_symlink():
            raise SelectionReceiptError("selection receipt must not be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise SelectionReceiptError("selection receipt does not exist") from error
        if not resolved.is_file():
            raise SelectionReceiptError("selection receipt must be a regular file")
        payload = resolved.read_bytes()
        if sha256_digest(payload) != digest:
            raise SelectionReceiptError("selection receipt file digest differs")
        record = _read_json(payload, "selection receipt")
        if not isinstance(record, Mapping) or _canonical_bytes(record) != payload:
            raise SelectionReceiptError("selection receipt bytes are not canonical")
        receipt = SelectionReceipt.from_record(
            record,
            source_broader_edges=source_broader_edges,
            unselected_observation_ids=unselected_observation_ids,
        )
        if resolved.read_bytes() != payload:
            raise SelectionReceiptError("selection receipt changed while opening")
        return cls(
            path=resolved,
            file_digest=digest,
            receipt_id=receipt.identifier,
            content_digest=receipt.content_digest,
            scope_kind=receipt.scope_kind,
            _receipt=receipt,
        )

    def verified_receipt(self) -> SelectionReceipt:
        reopened = self.open(
            self.path,
            expected_file_digest=self.file_digest,
            source_broader_edges=self._receipt.source_broader_edges,
            unselected_observation_ids=self._receipt.unselected_observation_ids,
        )
        if (
            reopened.receipt_id != self.receipt_id
            or reopened.content_digest != self.content_digest
            or reopened.scope_kind != self.scope_kind
        ):
            raise SelectionReceiptError("selection receipt identity, digest, or scope kind changed")
        return reopened._receipt

    def pin(self) -> dict[str, str]:
        receipt = self.verified_receipt()
        return {
            "role": "SelectionReceipt",
            "id": receipt.identifier,
            "scopeKind": receipt.scope_kind,
            "contentDigest": receipt.content_digest,
            "fileDigest": self.file_digest,
        }


__all__ = [
    "SELECTION_RECEIPT_TYPE",
    "SELECTION_RECEIPT_VERSION",
    "BroaderEdgeDisposition",
    "PinnedSelectionReceipt",
    "SelectionReasonKind",
    "SelectionReceipt",
    "SelectionReceiptError",
    "SelectionScopeKind",
]

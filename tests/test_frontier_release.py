"""Pass 2 seals a complete subject frontier before candidate generation."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.frontier import PinnedSelectionReceipt, SelectionReceipt
from refspec.atlas.frontier_release import (
    FrontierReleaseError,
    cut_subject_frontier_release,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseError,
    SourceConceptReleaseView,
    build_source_concept_release_bundle,
    source_scoped_concept_iri,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

CAPTURED_AT = "2026-08-04T12:00:00Z"
SOURCE_ARTIFACT = "https://publisher.example/frontier/source.json"
SOURCE_SCHEME = "https://publisher.example/frontier/scheme"
EXTERNAL_PARENT = "https://publisher.example/frontier/concepts/external-parent"
REFERENCE_RELEASE = "urn:ref:test:frontier:reference-release:core"
SELECTOR = "urn:ref:test:frontier:selector:label:v1"


def _digest(label: str) -> str:
    return sha256_digest(label.encode("utf-8"))


def _local_record_id(index: int) -> str:
    return "urn:uuid:" + derive_uuid7(
        CAPTURED_AT,
        seed=f"frontier-release-local-record:{index}".encode(),
    )


def _observation(index: int) -> dict[str, Any]:
    return {
        "id": f"urn:ref:test:frontier:observation:{index}",
        "sourceArtifact": SOURCE_ARTIFACT,
        "sourcePath": f"terms/{index}",
        "sourceOrdinal": index,
        "labels": [
            {
                "value": f"Frontier term {index}",
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": [],
        "uses": ["candidateGeneration", "mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": _local_record_id(index),
    }


def _source(
    *,
    resource_id: str = "frontier-release-source",
    observations: Sequence[Mapping[str, Any]] | None = None,
) -> SourceControlledResourceBundle:
    rows = tuple(_observation(index) for index in (1, 2, 3)) if observations is None else tuple(observations)
    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title="Frontier release source",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("candidateGeneration", "mappingReference"),
        captured_at=CAPTURED_AT,
        observations=rows,
        source_artifacts={SOURCE_ARTIFACT: b'{"terms":[1,2,3]}\n'},
        source_scheme={
            "id": SOURCE_SCHEME,
            "code": "frontier-test",
            "label": "Frontier test scheme",
            "sourceArtifact": SOURCE_ARTIFACT,
            "sourceFetchId": derive_uuid7(
                CAPTURED_AT,
                seed=b"frontier-release-source-fetch",
            ),
            "sourceObservedAt": CAPTURED_AT,
        },
    )


def _concept_id(index: int) -> str:
    return source_scoped_concept_iri(SOURCE_SCHEME, _local_record_id(index))


def _source_capture(source: SourceControlledResourceBundle) -> dict[str, Any]:
    artifacts = source.artifact_bytes()
    coverage = source.coverage_report
    return {
        "role": "SourceControlledResourceCapture",
        "resourceManifest": source.resource_manifest["id"],
        "logicalDigest": source.logical_digest,
        "bundleManifestDigest": sha256_digest(artifacts["bundle-manifest.json"]),
        "observationSetDigest": source.resource_manifest["observationSetDigest"],
        "coverageReportDigest": sha256_digest(artifacts["coverage-report.json"]),
        "distributionCoverage": "complete",
        "coverageStatus": coverage["reportStatus"],
        "sourceObservedCount": coverage["sourceObservedCount"],
        "parsedObservationCount": coverage["parsedCount"],
        "packagedObservationCount": coverage["packagedCount"],
        "excludedObservationCount": coverage["excludedCount"],
        "failedObservationCount": coverage["failedCount"],
        "gapCount": len(coverage["gaps"]),
    }


def _reference_inputs() -> list[dict[str, Any]]:
    return [
        {
            "release": {
                "releaseKind": "sourceConceptRelease",
                "semanticRing": "subject",
                "releaseId": REFERENCE_RELEASE,
                "manifestDigest": _digest("reference-manifest"),
                "releaseDigest": _digest("reference-release"),
                "logicalDigest": _digest("reference-logical"),
            },
            "atlasIndex": {
                "role": "AtlasIndex",
                "id": "urn:ref:test:frontier:atlas-index:v1",
                "indexDigest": _digest("atlas-index"),
                "fileDigest": _digest("atlas-index-file"),
            },
            "participationRow": {
                "rowId": "urn:ref:test:frontier:atlas-index-row:core",
                "rowDigest": _digest("atlas-index-row"),
                "releaseId": REFERENCE_RELEASE,
                "atlasParticipation": "core",
            },
        }
    ]


def _policy() -> dict[str, Any]:
    return {
        "id": "urn:ref:test:frontier:selection-policy:v1",
        "version": "1.0.0",
        "selectors": [
            {
                "id": SELECTOR,
                "version": "1.0.0",
                "parameters": {"caseFold": True},
            }
        ],
        "hierarchyDepth": 1,
        "compilerDigest": _digest("frontier-compiler"),
    }


def _selected_concepts() -> list[dict[str, Any]]:
    return [
        {
            "conceptId": _concept_id(1),
            "sourceObservationId": _observation(1)["id"],
            "reasons": [
                {
                    "kind": "predicateMatch",
                    "selector": SELECTOR,
                    "referenceRelease": REFERENCE_RELEASE,
                    "referenceConcept": "urn:ref:test:frontier:reference-concept:1",
                }
            ],
        },
        {
            "conceptId": _concept_id(3),
            "sourceObservationId": _observation(3)["id"],
            "reasons": [
                {
                    "kind": "hierarchyContext",
                    "seedConcept": _concept_id(1),
                    "depth": 1,
                }
            ],
        },
    ]


def _source_edges() -> list[dict[str, str]]:
    return [
        {
            "narrowerConcept": _concept_id(1),
            "broaderConcept": _concept_id(3),
        },
        {
            "narrowerConcept": _concept_id(3),
            "broaderConcept": EXTERNAL_PARENT,
        },
    ]


def _edge_dispositions() -> list[dict[str, str]]:
    return [
        {
            "narrowerConcept": _concept_id(1),
            "broaderConcept": _concept_id(3),
            "disposition": "included",
            "reason": "Both endpoints are selected.",
        },
        {
            "narrowerConcept": _concept_id(3),
            "broaderConcept": EXTERNAL_PARENT,
            "disposition": "omitted",
            "reason": "The edge crosses the declared hierarchy boundary.",
        },
    ]


def _receipt(
    source: SourceControlledResourceBundle,
    *,
    selected_concepts: Sequence[Mapping[str, Any]] | None = None,
    source_edges: Sequence[Mapping[str, str]] | None = None,
    edge_dispositions: Sequence[Mapping[str, str]] | None = None,
    source_capture: Mapping[str, Any] | None = None,
    unselected_observation_ids: Sequence[str] | None = None,
) -> SelectionReceipt:
    return SelectionReceipt.create(
        scope_kind="policyFrontier",
        source_capture=_source_capture(source) if source_capture is None else source_capture,
        reference_inputs=_reference_inputs(),
        selection_policy=_policy(),
        selected_concepts=(_selected_concepts() if selected_concepts is None else selected_concepts),
        broader_edge_dispositions=(_edge_dispositions() if edge_dispositions is None else edge_dispositions),
        source_broader_edges=_source_edges() if source_edges is None else source_edges,
        unselected_observation_ids=(
            (_observation(2)["id"],) if unselected_observation_ids is None else unselected_observation_ids
        ),
    )


def _pinned_receipt(
    tmp_path: Path,
    source: SourceControlledResourceBundle,
    *,
    selected_concepts: Sequence[Mapping[str, Any]] | None = None,
    source_edges: Sequence[Mapping[str, str]] | None = None,
    edge_dispositions: Sequence[Mapping[str, str]] | None = None,
    source_capture: Mapping[str, Any] | None = None,
    unselected_observation_ids: Sequence[str] | None = None,
) -> tuple[SelectionReceipt, PinnedSelectionReceipt]:
    edges = _source_edges() if source_edges is None else list(source_edges)
    unselected = (_observation(2)["id"],) if unselected_observation_ids is None else tuple(unselected_observation_ids)
    receipt = _receipt(
        source,
        selected_concepts=selected_concepts,
        source_edges=edges,
        edge_dispositions=edge_dispositions,
        source_capture=source_capture,
        unselected_observation_ids=unselected,
    )
    path = receipt.write_to(tmp_path / "selection-receipt.json")
    return receipt, PinnedSelectionReceipt.open(
        path,
        expected_file_digest=sha256_digest(path.read_bytes()),
        source_broader_edges=edges,
        unselected_observation_ids=unselected,
    )


def _rights(source: SourceControlledResourceBundle) -> tuple[dict[str, Any], ...]:
    return (
        {
            "type": "RightsMetadata",
            "rightsStatus": "notStated",
            "sourceArtifact": SOURCE_ARTIFACT,
            "sourceDigest": sha256_digest(source.source_artifacts[SOURCE_ARTIFACT]),
        },
    )


def test_pass_two_cuts_and_reopens_one_complete_frontier_release(
    tmp_path: Path,
) -> None:
    source = _source()
    receipt, pinned = _pinned_receipt(tmp_path, source)

    release = cut_subject_frontier_release(
        source,
        selection_receipt=pinned,
        rights_metadata=_rights(source),
    )

    assert release.semantic_ring == "subject"
    assert release.release_manifest["scopeKind"] == "policyFrontier"
    assert release.release_manifest["selectionPolicy"] == {
        "id": _policy()["id"],
        "type": "policyFrontier",
        "selectionReceipt": pinned.pin(),
    }
    assert release.release_manifest["scopeAccounting"] == {
        "distributionCoverage": "complete",
        "sourceCoverageStatus": "pass",
        "sourceObservedCount": 3,
        "sourceParsedObservationCount": 3,
        "sourcePackagedObservationCount": 3,
        "sourceExcludedObservationCount": 0,
        "sourceFailedObservationCount": 0,
        "sourceGapCount": 0,
        "selectedObservationCount": 2,
        "unselectedObservationCount": 1,
        "sourceBroaderEdgeCount": 2,
        "includedBroaderEdgeCount": 1,
        "externalReferenceBroaderEdgeCount": 0,
        "omittedBroaderEdgeCount": 1,
    }
    assert release.artifact_bytes()["selection-receipt.json"] == receipt.artifact_bytes()
    assert {str(row["sourceObservation"]) for row in release.concepts} == {
        _observation(1)["id"],
        _observation(3)["id"],
    }
    assert {str(row["id"]) for row in release.concepts} == {
        _concept_id(1),
        _concept_id(3),
    }
    assert len(release.source_bundle.observations) == 3

    root = release.write_to(tmp_path / "frontier-release")
    reopened = SourceConceptReleaseView.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=release.manifest_digest,
    )
    assert reopened.bundle.artifact_bytes() == release.artifact_bytes()
    assert reopened.selection_receipt == receipt.record


def test_pass_two_is_order_independent_and_content_derived(tmp_path: Path) -> None:
    source = _source()
    _, first_pin = _pinned_receipt(tmp_path / "first", source)
    _, second_pin = _pinned_receipt(
        tmp_path / "second",
        source,
        selected_concepts=tuple(reversed(_selected_concepts())),
        source_edges=tuple(reversed(_source_edges())),
        edge_dispositions=tuple(reversed(_edge_dispositions())),
    )

    first = cut_subject_frontier_release(
        source,
        selection_receipt=first_pin,
        rights_metadata=_rights(source),
    )
    second = cut_subject_frontier_release(
        source,
        selection_receipt=second_pin,
        rights_metadata=_rights(source),
    )

    assert first.release_id == second.release_id
    assert first.artifact_bytes() == second.artifact_bytes()


@pytest.mark.parametrize("mode", ("wrong", "swapped"))
def test_receipt_member_pairs_must_match_preserved_source_identities(
    tmp_path: Path,
    mode: str,
) -> None:
    source = _source()
    selected = copy.deepcopy(_selected_concepts())
    source_edges = _source_edges()
    dispositions = _edge_dispositions()
    if mode == "wrong":
        original = selected[0]["conceptId"]
        selected[0]["conceptId"] = "urn:ref:test:frontier:wrong-concept"
        selected[1]["reasons"][0]["seedConcept"] = selected[0]["conceptId"]
        for edge in source_edges:
            if edge["narrowerConcept"] == original:
                edge["narrowerConcept"] = selected[0]["conceptId"]
            if edge["broaderConcept"] == original:
                edge["broaderConcept"] = selected[0]["conceptId"]
        for edge in dispositions:
            if edge["narrowerConcept"] == original:
                edge["narrowerConcept"] = selected[0]["conceptId"]
            if edge["broaderConcept"] == original:
                edge["broaderConcept"] = selected[0]["conceptId"]
    else:
        selected[0]["conceptId"], selected[1]["conceptId"] = (
            selected[1]["conceptId"],
            selected[0]["conceptId"],
        )
        selected[1]["reasons"][0]["seedConcept"] = selected[0]["conceptId"]
    _, pinned = _pinned_receipt(
        tmp_path,
        source,
        selected_concepts=selected,
        source_edges=source_edges,
        edge_dispositions=dispositions,
    )

    with pytest.raises(FrontierReleaseError, match="concept and source-observation pairs differ"):
        cut_subject_frontier_release(
            source,
            selection_receipt=pinned,
            rights_metadata=_rights(source),
        )


def test_receipt_must_name_the_exact_nested_source_capture(tmp_path: Path) -> None:
    source = _source()
    _, pinned = _pinned_receipt(tmp_path, source)
    other_source = _source(resource_id="different-frontier-source")

    with pytest.raises(FrontierReleaseError, match="sourceCapture.resourceManifest differs"):
        cut_subject_frontier_release(
            other_source,
            selection_receipt=pinned,
            rights_metadata=_rights(other_source),
        )


def test_receipt_cannot_balance_an_unknown_selected_observation(
    tmp_path: Path,
) -> None:
    source = _source()
    selected = copy.deepcopy(_selected_concepts())
    selected[0]["sourceObservationId"] = "urn:ref:test:frontier:observation:unknown"
    _, pinned = _pinned_receipt(tmp_path, source, selected_concepts=selected)

    with pytest.raises(FrontierReleaseError, match="outside the exact source capture"):
        cut_subject_frontier_release(
            source,
            selection_receipt=pinned,
            rights_metadata=_rights(source),
        )


def test_receipt_source_counts_must_reproduce_from_the_nested_capture(
    tmp_path: Path,
) -> None:
    source = _source()
    source_capture = _source_capture(source)
    source_capture.update(
        {
            "coverageStatus": "gap",
            "sourceObservedCount": 4,
            "excludedObservationCount": 1,
            "gapCount": 1,
        }
    )
    _, pinned = _pinned_receipt(
        tmp_path,
        source,
        source_capture=source_capture,
    )

    with pytest.raises(FrontierReleaseError, match="sourceCapture.coverageStatus differs"):
        cut_subject_frontier_release(
            source,
            selection_receipt=pinned,
            rights_metadata=_rights(source),
        )


def test_frontier_selection_requires_complete_distribution_coverage(
    tmp_path: Path,
) -> None:
    source = _source()
    source_capture = _source_capture(source)
    source_capture["distributionCoverage"] = "partial"
    _, pinned = _pinned_receipt(
        tmp_path,
        source,
        source_capture=source_capture,
    )

    with pytest.raises(FrontierReleaseError, match="complete publisher-distribution coverage"):
        cut_subject_frontier_release(
            source,
            selection_receipt=pinned,
            rights_metadata=_rights(source),
        )


def test_receipt_pin_and_embedded_bytes_are_both_required(tmp_path: Path) -> None:
    source = _source()
    receipt, pinned = _pinned_receipt(tmp_path, source)
    bad_pin = pinned.pin()
    bad_pin["fileDigest"] = _digest("wrong-receipt-file")

    with pytest.raises(SourceConceptReleaseError, match="pin differs"):
        build_source_concept_release_bundle(
            source,
            semantic_ring="subject",
            selected_observation_ids=(_observation(1)["id"], _observation(3)["id"]),
            selection_policy={
                "id": _policy()["id"],
                "type": "policyFrontier",
                "selectionReceipt": bad_pin,
            },
            rights_metadata=_rights(source),
            selection_receipt=receipt.as_record(),
        )

    release = cut_subject_frontier_release(
        source,
        selection_receipt=pinned,
        rights_metadata=_rights(source),
    )
    root = release.write_to(tmp_path / "frontier-release")
    receipt_path = root / "selection-receipt.json"
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(SourceConceptReleaseError, match="bytes differ"):
        SourceConceptReleaseView.open(
            root / "bundle-manifest.json",
            expected_manifest_digest=release.manifest_digest,
        )


def test_pinned_receipt_drift_is_rejected_before_cutting(tmp_path: Path) -> None:
    source = _source()
    _, pinned = _pinned_receipt(tmp_path, source)
    pinned.path.write_bytes(pinned.path.read_bytes() + b" ")

    with pytest.raises(FrontierReleaseError, match="file digest differs"):
        cut_subject_frontier_release(
            source,
            selection_receipt=pinned,
            rights_metadata=_rights(source),
        )


def test_policy_frontier_is_subject_only_and_explicit_releases_carry_no_receipt(
    tmp_path: Path,
) -> None:
    source = _source()
    receipt, pinned = _pinned_receipt(tmp_path, source)
    policy = {
        "id": _policy()["id"],
        "type": "policyFrontier",
        "selectionReceipt": pinned.pin(),
    }
    with pytest.raises(SourceConceptReleaseError, match="must use the subject ring"):
        build_source_concept_release_bundle(
            source,
            semantic_ring="entity",
            selected_observation_ids=(_observation(1)["id"], _observation(3)["id"]),
            selection_policy=policy,
            rights_metadata=_rights(source),
            selection_receipt=receipt.as_record(),
        )

    with pytest.raises(SourceConceptReleaseError, match="must not contain a selection receipt"):
        build_source_concept_release_bundle(
            source,
            semantic_ring="subject",
            selected_observation_ids=(_observation(1)["id"], _observation(3)["id"]),
            selection_policy={
                "id": "urn:ref:test:explicit-selection:v1",
                "type": "explicitObservationSet",
            },
            rights_metadata=_rights(source),
            selection_receipt=receipt.as_record(),
        )

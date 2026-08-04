"""Selection receipts close verified subsets and policy frontiers exactly."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.frontier import (
    SELECTION_RECEIPT_TYPE,
    SELECTION_RECEIPT_VERSION,
    PinnedSelectionReceipt,
    SelectionReceipt,
    SelectionReceiptError,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

SELECTOR = "urn:ref:test:selector:normalized-label:v1"
SECOND_SELECTOR = "urn:ref:test:selector:notation-prefix:v1"
INDEX_ID = "urn:ref:test:atlas-index:v1"
RELEASE_A = "urn:ref:test:reference-release:core"
RELEASE_B = "urn:ref:test:reference-release:specialist"
CONCEPT_A = "urn:ref:test:frontier-concept:a"
CONCEPT_B = "urn:ref:test:frontier-concept:b"
CONCEPT_C = "urn:ref:test:frontier-concept:c"
EXTERNAL_A = "urn:ref:test:frontier-concept:external-a"
EXTERNAL_B = "urn:ref:test:frontier-concept:external-b"
OBSERVATION_A = "urn:ref:test:source-observation:a"
OBSERVATION_B = "urn:ref:test:source-observation:b"
OBSERVATION_C = "urn:ref:test:source-observation:c"
OBSERVATION_D = "urn:ref:test:source-observation:d"


def _digest(label: str) -> str:
    return sha256_digest(label.encode())


def _source_capture(*, packaged: int = 4, gaps: bool = True) -> dict[str, Any]:
    excluded = 1 if gaps else 0
    return {
        "role": "SourceControlledResourceCapture",
        "resourceManifest": "urn:ref:test:source-resource-manifest:frontier",
        "logicalDigest": _digest("source-logical"),
        "bundleManifestDigest": _digest("source-bundle-manifest"),
        "observationSetDigest": _digest("source-observations"),
        "coverageReportDigest": _digest("source-coverage"),
        "distributionCoverage": "complete",
        "coverageStatus": "gap" if gaps else "pass",
        "sourceObservedCount": packaged + excluded,
        "parsedObservationCount": packaged,
        "packagedObservationCount": packaged,
        "excludedObservationCount": excluded,
        "failedObservationCount": 0,
        "gapCount": excluded,
    }


def _reference_input(
    release_id: str,
    participation: str,
    suffix: str,
) -> dict[str, Any]:
    release = (
        {
            "releaseKind": "sourceConceptRelease",
            "semanticRing": "subject",
            "releaseId": release_id,
            "manifestDigest": _digest(f"release-manifest:{suffix}"),
            "releaseDigest": _digest(f"release:{suffix}"),
            "logicalDigest": _digest(f"release-logical:{suffix}"),
        }
        if participation == "core"
        else {
            "releaseKind": "managedReferenceRelease",
            "semanticRing": "subject",
            "releaseId": release_id,
            "manifestDigest": _digest(f"release-manifest:{suffix}"),
            "managedBundleReleaseId": f"urn:ref:test:managed-bundle:{suffix}",
            "ringAssignment": {
                "id": f"urn:ref:test:ring-assignment:{suffix}",
                "contentDigest": _digest(f"ring-assignment:{suffix}"),
                "fileDigest": _digest(f"ring-assignment-file:{suffix}"),
            },
            "rulespecGraph": {
                "id": f"urn:ref:test:rulespec-graph:{suffix}",
                "digest": _digest(f"rulespec-graph:{suffix}"),
            },
            "declaredReleaseDigest": _digest(f"declared-release:{suffix}"),
        }
    )
    return {
        "release": release,
        "atlasIndex": {
            "role": "AtlasIndex",
            "id": INDEX_ID,
            "indexDigest": _digest("atlas-index"),
            "fileDigest": _digest("atlas-index-file"),
        },
        "participationRow": {
            "rowId": f"urn:ref:test:atlas-index-row:{suffix}",
            "rowDigest": _digest(f"atlas-index-row:{suffix}"),
            "releaseId": release_id,
            "atlasParticipation": participation,
        },
    }


def _reference_inputs() -> list[dict[str, Any]]:
    return [
        _reference_input(RELEASE_A, "core", "core"),
        _reference_input(RELEASE_B, "specialist", "specialist"),
    ]


def _policy() -> dict[str, Any]:
    return {
        "id": "urn:ref:test:frontier-selection-policy:v1",
        "version": "1.0.0",
        "selectors": [
            {
                "id": SELECTOR,
                "version": "1.2.0",
                "parameters": {
                    "caseFold": True,
                    "languages": ["en", "es"],
                    "minimumTokenLength": 3,
                },
            },
            {
                "id": SECOND_SELECTOR,
                "version": "2.0.0",
                "parameters": {"prefixes": ["A", "B"]},
            },
        ],
        "hierarchyDepth": 2,
        "compilerDigest": _digest("frontier-compiler-v1"),
    }


def _selected_concepts() -> list[dict[str, Any]]:
    return [
        {
            "conceptId": CONCEPT_A,
            "sourceObservationId": OBSERVATION_A,
            "reasons": [
                {
                    "kind": "predicateMatch",
                    "selector": SELECTOR,
                    "referenceRelease": RELEASE_A,
                    "referenceConcept": "urn:ref:test:core-concept:a",
                }
            ],
        },
        {
            "conceptId": CONCEPT_B,
            "sourceObservationId": OBSERVATION_B,
            "reasons": [
                {
                    "kind": "publisherMappingEndpoint",
                    "mapping": "urn:ref:test:publisher-mapping:b",
                }
            ],
        },
        {
            "conceptId": CONCEPT_C,
            "sourceObservationId": OBSERVATION_C,
            "reasons": [
                {
                    "kind": "hierarchyContext",
                    "seedConcept": CONCEPT_A,
                    "depth": 1,
                }
            ],
        },
    ]


def _source_edges() -> list[dict[str, str]]:
    return [
        {"narrowerConcept": CONCEPT_A, "broaderConcept": CONCEPT_B},
        {"narrowerConcept": CONCEPT_B, "broaderConcept": EXTERNAL_A},
        {"narrowerConcept": CONCEPT_C, "broaderConcept": EXTERNAL_B},
    ]


def _edge_dispositions() -> list[dict[str, Any]]:
    return [
        {
            "narrowerConcept": CONCEPT_A,
            "broaderConcept": CONCEPT_B,
            "disposition": "included",
            "reason": "Both endpoints are selected within the declared depth.",
        },
        {
            "narrowerConcept": CONCEPT_B,
            "broaderConcept": EXTERNAL_A,
            "disposition": "omitted",
            "reason": "The edge crosses the declared hierarchy boundary.",
        },
        {
            "narrowerConcept": CONCEPT_C,
            "broaderConcept": EXTERNAL_B,
            "disposition": "externalReference",
            "reason": "The external parent remains visible without joining the release.",
        },
    ]


def _arguments() -> dict[str, Any]:
    return {
        "scope_kind": "policyFrontier",
        "source_capture": _source_capture(),
        "reference_inputs": _reference_inputs(),
        "selection_policy": _policy(),
        "selected_concepts": _selected_concepts(),
        "broader_edge_dispositions": _edge_dispositions(),
        "source_broader_edges": _source_edges(),
        "unselected_observation_ids": [OBSERVATION_D],
    }


def _receipt(**changes: Any) -> SelectionReceipt:
    arguments = _arguments()
    arguments.update(changes)
    return SelectionReceipt.create(**arguments)


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _all_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_policy_frontier_receipt_is_deterministic_typed_and_content_derived() -> None:
    first = _receipt()
    reordered_policy = _policy()
    reordered_policy["selectors"].reverse()
    second = _receipt(
        reference_inputs=list(reversed(_reference_inputs())),
        selection_policy=reordered_policy,
        selected_concepts=list(reversed(_selected_concepts())),
        broader_edge_dispositions=list(reversed(_edge_dispositions())),
        source_broader_edges=list(reversed(_source_edges())),
    )

    assert first.as_record() == second.as_record()
    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.as_record()["type"] == SELECTION_RECEIPT_TYPE
    assert first.as_record()["schemaVersion"] == SELECTION_RECEIPT_VERSION
    assert first.scope_kind == "policyFrontier"
    assert first.identifier.startswith("urn:ref:atlas-selection-receipt:")
    assert first.as_record()["counts"] == {
        "selectedConcepts": 3,
        "unselectedObservations": 1,
        "broaderEdges": 3,
        "includedBroaderEdges": 1,
        "externalReferenceBroaderEdges": 1,
        "omittedBroaderEdges": 1,
    }
    assert first.as_record()["unselectedObservationIdsDigest"] == sha256_digest(canonical_json_bytes([OBSERVATION_D]))
    assert first.as_record()["sourceBroaderEdgesDigest"] == sha256_digest(canonical_json_bytes(_source_edges()))
    managed_release = next(
        item["release"]
        for item in first.as_record()["referenceInputs"]
        if item["release"]["releaseKind"] == "managedReferenceRelease"
    )
    assert set(managed_release) == {
        "releaseKind",
        "semanticRing",
        "releaseId",
        "manifestDigest",
        "managedBundleReleaseId",
        "ringAssignment",
        "rulespecGraph",
        "declaredReleaseDigest",
    }
    assert all(
        item["atlasIndex"]["fileDigest"] == _digest("atlas-index-file") for item in first.as_record()["referenceInputs"]
    )
    basis = first.as_record()
    basis.pop("id")
    basis.pop("contentDigest")
    assert first.content_digest == sha256_digest(canonical_json_bytes(basis))
    assert _all_keys(first.as_record()).isdisjoint({"createdAt", "selectedAt", "generatedAt", "authorized", "admitted"})


def test_receipt_views_and_dataclass_are_immutable() -> None:
    receipt = _receipt()

    with pytest.raises(TypeError):
        receipt.record["scopeKind"] = "verifiedSubset"  # type: ignore[index]
    with pytest.raises(TypeError):
        receipt.record["sourceCapture"]["coverageStatus"] = "pass"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        receipt.record = {}  # type: ignore[misc]
    assert isinstance(receipt.record["selectedConcepts"], tuple)
    assert isinstance(receipt.source_broader_edges, tuple)


def test_verified_subset_may_be_source_local_without_reference_releases() -> None:
    selected = [
        {
            "conceptId": CONCEPT_A,
            "sourceObservationId": OBSERVATION_A,
            "reasons": [
                {
                    "kind": "publisherMappingEndpoint",
                    "mapping": "urn:ref:test:verified-subset-membership:a",
                }
            ],
        }
    ]
    receipt = SelectionReceipt.create(
        scope_kind="verifiedSubset",
        source_capture=_source_capture(packaged=2, gaps=False),
        selection_policy=_policy(),
        selected_concepts=selected,
        broader_edge_dispositions=(),
        source_broader_edges=(),
        unselected_observation_ids=(OBSERVATION_B,),
    )

    assert receipt.scope_kind == "verifiedSubset"
    assert receipt.as_record()["referenceInputs"] == []
    assert receipt.as_record()["counts"]["broaderEdges"] == 0


def test_policy_frontier_requires_an_exact_reference_release_and_row_pin() -> None:
    with pytest.raises(SelectionReceiptError, match="requires an exact reference release"):
        _receipt(reference_inputs=())

    references = _reference_inputs()
    references[0]["participationRow"]["releaseId"] = RELEASE_B
    with pytest.raises(SelectionReceiptError, match="differs from its reference release"):
        _receipt(reference_inputs=references)

    references = _reference_inputs()
    references[0]["participationRow"]["atlasParticipation"] = "bridge"
    with pytest.raises(SelectionReceiptError, match="must be core or specialist"):
        _receipt(reference_inputs=references)

    references = _reference_inputs()
    del references[0]["release"]["releaseDigest"]
    with pytest.raises(SelectionReceiptError, match="fields differ"):
        _receipt(reference_inputs=references)

    references = _reference_inputs()
    references[1]["atlasIndex"]["fileDigest"] = _digest("other-index-file")
    with pytest.raises(SelectionReceiptError, match="one exact atlas index"):
        _receipt(reference_inputs=references)


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("top", "createdAt"),
        ("source", "authorization"),
        ("release", "label"),
        ("index", "path"),
        ("participation", "sourceModule"),
        ("policy", "generatedAt"),
        ("selector", "implementation"),
        ("selected", "score"),
        ("reason", "confidence"),
        ("edge", "predicate"),
        ("counts", "sourceTotal"),
    ],
)
def test_receipt_rejects_unknown_fields_at_every_structural_level(
    location: str,
    field: str,
) -> None:
    receipt = _receipt()
    record = receipt.as_record()
    targets: dict[str, dict[str, Any]] = {
        "top": record,
        "source": record["sourceCapture"],
        "release": record["referenceInputs"][0]["release"],
        "index": record["referenceInputs"][0]["atlasIndex"],
        "participation": record["referenceInputs"][0]["participationRow"],
        "policy": record["selectionPolicy"],
        "selector": record["selectionPolicy"]["selectors"][0],
        "selected": record["selectedConcepts"][0],
        "reason": record["selectedConcepts"][0]["reasons"][0],
        "edge": record["broaderEdgeDispositions"][0],
        "counts": record["counts"],
    }
    targets[location][field] = "forbidden"

    with pytest.raises(SelectionReceiptError, match="fields differ"):
        SelectionReceipt.from_record(
            record,
            source_broader_edges=_source_edges(),
            unselected_observation_ids=(OBSERVATION_D,),
        )


def test_receipt_rejects_forged_identity_and_stale_counts() -> None:
    receipt = _receipt()
    record = receipt.as_record()
    record["contentDigest"] = _digest("forged")
    with pytest.raises(SelectionReceiptError, match="content identity"):
        SelectionReceipt.from_record(
            record,
            source_broader_edges=_source_edges(),
            unselected_observation_ids=(OBSERVATION_D,),
        )

    record = receipt.as_record()
    record["counts"]["selectedConcepts"] = 99
    with pytest.raises(SelectionReceiptError, match="counts.selectedConcepts differs"):
        SelectionReceipt.from_record(
            record,
            source_broader_edges=_source_edges(),
            unselected_observation_ids=(OBSERVATION_D,),
        )


def test_receipt_closes_the_selected_and_unselected_observation_sets() -> None:
    with pytest.raises(SelectionReceiptError, match="overlap"):
        _receipt(unselected_observation_ids=(OBSERVATION_A,))

    with pytest.raises(SelectionReceiptError, match="unique identifiers"):
        _receipt(unselected_observation_ids=(OBSERVATION_D, OBSERVATION_D))

    with pytest.raises(SelectionReceiptError, match="every packaged source observation"):
        _receipt(unselected_observation_ids=())

    receipt = _receipt()
    with pytest.raises(SelectionReceiptError, match="content identity"):
        SelectionReceipt.from_record(
            receipt.as_record(),
            source_broader_edges=_source_edges(),
            unselected_observation_ids=("urn:ref:test:source-observation:other",),
        )


def test_receipt_requires_one_disposition_for_every_exact_source_broader_edge() -> None:
    with pytest.raises(SelectionReceiptError, match="differ from the exact source edge set"):
        _receipt(broader_edge_dispositions=_edge_dispositions()[:-1])

    with pytest.raises(SelectionReceiptError, match="differ from the exact source edge set"):
        _receipt(source_broader_edges=_source_edges()[:-1])

    edges = _edge_dispositions()
    edges[1]["disposition"] = "included"
    with pytest.raises(SelectionReceiptError, match="must also be selected"):
        _receipt(broader_edge_dispositions=edges)

    edges = _edge_dispositions()
    edges[0]["disposition"] = "externalReference"
    with pytest.raises(SelectionReceiptError, match="must use the included disposition"):
        _receipt(broader_edge_dispositions=edges)

    edges = _edge_dispositions()
    edges[0]["reason"] = " "
    with pytest.raises(SelectionReceiptError, match="non-empty trimmed text"):
        _receipt(broader_edge_dispositions=edges)


def test_receipt_rejects_untyped_or_unpinned_selection_reasons() -> None:
    selected = _selected_concepts()
    selected[0]["reasons"][0]["kind"] = "labelSimilarity"
    with pytest.raises(SelectionReceiptError, match="kind is unsupported"):
        _receipt(selected_concepts=selected)

    selected = _selected_concepts()
    selected[0]["reasons"][0]["selector"] = "urn:ref:test:selector:unlisted"
    with pytest.raises(SelectionReceiptError, match="absent from the pinned selection policy"):
        _receipt(selected_concepts=selected)

    selected = _selected_concepts()
    selected[0]["reasons"][0]["referenceRelease"] = "urn:ref:test:reference-release:unlisted"
    with pytest.raises(SelectionReceiptError, match="absent from the exact reference inputs"):
        _receipt(selected_concepts=selected)

    selected = _selected_concepts()
    selected[2]["reasons"][0]["depth"] = 3
    with pytest.raises(SelectionReceiptError, match="between 1"):
        _receipt(selected_concepts=selected)

    selected = _selected_concepts()
    selected[2]["reasons"][0]["seedConcept"] = CONCEPT_C
    with pytest.raises(SelectionReceiptError, match="another selected concept"):
        _receipt(selected_concepts=selected)


def test_source_capture_coverage_is_exact_and_honest() -> None:
    source = _source_capture()
    source["sourceObservedCount"] = 99
    with pytest.raises(SelectionReceiptError, match="does not account"):
        _receipt(source_capture=source)

    source = _source_capture()
    source["coverageStatus"] = "pass"
    with pytest.raises(SelectionReceiptError, match="disagrees with its gaps"):
        _receipt(source_capture=source)

    source = _source_capture(gaps=False)
    source["distributionCoverage"] = "unknown"
    with pytest.raises(SelectionReceiptError, match="complete or partial"):
        _receipt(source_capture=source)


def test_pinned_receipt_reopens_exact_canonical_bytes_and_fails_on_drift(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    path = receipt.write_to(tmp_path / "selection-receipt.json")
    file_digest = sha256_digest(path.read_bytes())
    pinned = PinnedSelectionReceipt.open(
        path,
        expected_file_digest=file_digest,
        source_broader_edges=_source_edges(),
        unselected_observation_ids=(OBSERVATION_D,),
    )

    assert pinned.verified_receipt().as_record() == receipt.as_record()
    assert pinned.pin() == {
        "role": "SelectionReceipt",
        "id": receipt.identifier,
        "scopeKind": "policyFrontier",
        "contentDigest": receipt.content_digest,
        "fileDigest": file_digest,
    }
    assert str(tmp_path) not in repr(pinned.pin())

    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SelectionReceiptError, match="file digest differs"):
        pinned.verified_receipt()


def test_pinned_receipt_rejects_wrong_evidence_noncanonical_bytes_and_symlinks(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    canonical_path = receipt.write_to(tmp_path / "selection-receipt.json")
    canonical_digest = sha256_digest(canonical_path.read_bytes())

    with pytest.raises(SelectionReceiptError, match="content identity"):
        PinnedSelectionReceipt.open(
            canonical_path,
            expected_file_digest=canonical_digest,
            source_broader_edges=_source_edges(),
            unselected_observation_ids=("urn:ref:test:source-observation:wrong",),
        )

    pretty_path = tmp_path / "pretty-selection-receipt.json"
    pretty_path.write_text(json.dumps(receipt.as_record(), indent=2), encoding="utf-8")
    with pytest.raises(SelectionReceiptError, match="not canonical"):
        PinnedSelectionReceipt.open(
            pretty_path,
            expected_file_digest=sha256_digest(pretty_path.read_bytes()),
            source_broader_edges=_source_edges(),
            unselected_observation_ids=(OBSERVATION_D,),
        )

    symlink = tmp_path / "selection-receipt-link.json"
    symlink.symlink_to(canonical_path)
    with pytest.raises(SelectionReceiptError, match="must not be a symlink"):
        PinnedSelectionReceipt.open(
            symlink,
            expected_file_digest=canonical_digest,
            source_broader_edges=_source_edges(),
            unselected_observation_ids=(OBSERVATION_D,),
        )


def test_receipt_write_refuses_to_overwrite(tmp_path: Path) -> None:
    receipt = _receipt()
    path = receipt.write_to(tmp_path / "selection-receipt.json")

    with pytest.raises(SelectionReceiptError, match="already exists"):
        receipt.write_to(path)


def test_record_round_trip_does_not_depend_on_caller_owned_values() -> None:
    arguments = _arguments()
    original = copy.deepcopy(arguments)
    receipt = SelectionReceipt.create(**arguments)

    arguments["source_capture"]["coverageStatus"] = "pass"
    arguments["selection_policy"]["selectors"][0]["parameters"]["caseFold"] = False
    arguments["selected_concepts"][0]["conceptId"] = "urn:ref:test:mutated"
    arguments["source_broader_edges"].clear()

    expected = SelectionReceipt.create(**original)
    assert receipt.as_record() == expected.as_record()
    receipt.verify()

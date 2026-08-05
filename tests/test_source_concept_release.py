"""Shared source-concept releases make identity explicit in all four rings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas.concept_release import (
    ConceptReleaseError,
    concept_release_pin,
    normalize_concept_release_pin,
)
from refspec.registry.infrastructure.source_concept_release import (
    SOURCE_CONCEPT_IDENTITY_POLICY_ID,
    SOURCE_CONCEPT_RELEASE_LINEAGE_VERSION,
    SOURCE_RELEASE_SUPERSESSION_TYPE,
    SOURCE_RELEASE_SUPERSESSION_VERSION,
    SourceConceptReleaseBundle,
    SourceConceptReleaseError,
    SourceConceptReleaseView,
    build_source_concept_release_bundle,
    source_scoped_concept_iri,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    SourceControlledResourceError,
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

CAPTURED_AT = "2026-08-04T12:00:00Z"
SOURCE_ID = "https://publisher.example/source/terms.json"
SCHEME_ID = "https://publisher.example/schemes/example"
SELECTION_POLICY = {
    "id": "urn:ref:test:source-concept-selection:v1",
    "type": "explicitObservationSet",
}


def _local_record_id(index: int) -> str:
    return "urn:uuid:" + derive_uuid7(
        CAPTURED_AT,
        seed=f"source-concept-local-record:{index}".encode(),
    )


def _observation(
    index: int,
    *,
    label: str,
    local_record_id: str | None = None,
    publisher_concept_iri: str | None = None,
    publisher_source_digest: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"urn:ref:test:source-observation:{index}",
        "sourceArtifact": SOURCE_ID,
        "sourcePath": f"terms/{index}",
        "sourceOrdinal": index,
        "labels": [
            {
                "value": label,
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
    }
    if local_record_id is not None:
        row["localRecordId"] = local_record_id
    if publisher_concept_iri is not None:
        if publisher_source_digest is None:
            raise ValueError("publisher_source_digest is required with publisher identity")
        row["identifiers"].append(
            {
                "value": publisher_concept_iri,
                "kind": "publisherConceptIri",
                "authorityUri": SCHEME_ID,
                "sourceUri": SOURCE_ID,
                "sourcePath": f"terms/{index}",
                "observedAt": CAPTURED_AT,
                "sourceDigest": publisher_source_digest,
            }
        )
    return row


def _source(
    observations: Sequence[Mapping[str, Any]],
    *,
    payload: bytes = b'{"terms":["alpha","beta"]}\n',
    resource_id: str = "source-concept-test-capture",
) -> SourceControlledResourceBundle:
    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title="Source concept test observations",
        resource_kind="sourceTermSnapshot",
        identity_status="mixed",
        uses=("mappingReference",),
        captured_at=CAPTURED_AT,
        observations=observations,
        source_artifacts={SOURCE_ID: payload},
        source_scheme={
            "id": SCHEME_ID,
            "code": "example",
            "label": "Example source scheme",
            "sourceArtifact": SOURCE_ID,
            "sourceFetchId": derive_uuid7(
                CAPTURED_AT,
                seed=b"source-concept-scheme-fetch",
            ),
            "sourceObservedAt": CAPTURED_AT,
        },
    )


def _build(
    source: SourceControlledResourceBundle,
    *,
    ring: str = "subject",
    selected: Sequence[str] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    lifecycle: Sequence[Mapping[str, Any]] = (),
    rights: Sequence[Mapping[str, Any]] | None = None,
    supersedes: Sequence[SourceConceptReleaseBundle] = (),
):
    selected_ids = tuple(str(row["id"]) for row in source.observations) if selected is None else tuple(selected)
    selected_artifacts = {
        str(row["sourceArtifact"]) for row in source.observations if str(row["id"]) in set(selected_ids)
    }
    rights_metadata = (
        tuple(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": identifier,
                "sourceDigest": "sha256:" + hashlib.sha256(source.source_artifacts[identifier]).hexdigest(),
            }
            for identifier in sorted(selected_artifacts)
        )
        if rights is None
        else rights
    )
    return build_source_concept_release_bundle(
        source,
        semantic_ring=ring,  # type: ignore[arg-type]
        selected_observation_ids=selected_ids,
        selection_policy=SELECTION_POLICY,
        rights_metadata=rights_metadata,
        reconciliation_record=reconciliation,
        lifecycle_records=lifecycle,
        supersedes=supersedes,
    )


def _mapping_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {key for child in value.values() for key in _mapping_keys(child)}
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _mapping_keys(child)}
    return set()


@pytest.mark.parametrize(
    "ring",
    ("subject", "entity", "value", "legalIdentity"),
)
def test_one_release_shape_serves_all_four_semantic_rings(ring: str) -> None:
    observation = _observation(
        1,
        label="Stable meaning",
        local_record_id=_local_record_id(1),
    )
    source = _source((observation,))
    release = _build(source, ring=ring)

    assert release.semantic_ring == ring
    assert release.release_manifest["membershipMode"] == "completeMembership"
    assert release.release_manifest["identityPolicy"]["id"] == (SOURCE_CONCEPT_IDENTITY_POLICY_ID)
    assert release.release_manifest["rightsRecordCount"] == 1
    assert release.release_manifest["rightsSetDigest"].startswith("sha256:")
    assert release.release_manifest["sourceCapture"] == {
        "resourceManifest": source.resource_manifest["id"],
        "logicalDigest": source.logical_digest,
        "observationSetDigest": source.resource_manifest["observationSetDigest"],
    }
    assert release.concepts[0]["semanticRing"] == ring
    assert release.concepts[0]["sourceObservation"] == observation["id"]
    assert release.rights_metadata[0]["rightsStatus"] == "notStated"
    assert b'"rightsStatus":"notStated"' in release.artifact_bytes()["rights.jsonl"]
    assert release.concepts[0]["id"] == source_scoped_concept_iri(
        SCHEME_ID,
        str(observation["localRecordId"]),
    )
    forbidden = {
        "acceptedOutputAllowed",
        "acceptedOutputUseAuthorized",
        "admission",
        "candidateLookupAllowed",
        "candidateUseAuthorized",
        "emissionAuthorized",
        "outputProfile",
        "permission",
        "usageCeiling",
    }
    assert (
        not (
            _mapping_keys(release.release_manifest)
            | _mapping_keys(release.concepts)
            | _mapping_keys(release.lifecycle_records)
        )
        & forbidden
    )
    assert b"LocalConcept" not in b"".join(release.artifact_bytes().values())


def test_release_requires_exact_digest_pinned_rights_coverage() -> None:
    source = _source(
        (
            _observation(
                1,
                label="Rights-covered concept",
                local_record_id=_local_record_id(1),
            ),
        )
    )

    with pytest.raises(SourceConceptReleaseError, match="requires explicit rights metadata"):
        _build(source, rights=())
    with pytest.raises(SourceConceptReleaseError, match="sourceDigest differs"):
        _build(
            source,
            rights=(
                {
                    "type": "RightsMetadata",
                    "rightsStatus": "notStated",
                    "sourceArtifact": SOURCE_ID,
                    "sourceDigest": "sha256:" + "0" * 64,
                },
            ),
        )
    with pytest.raises(SourceConceptReleaseError, match="must exactly cover"):
        _build(
            source,
            rights=(
                {
                    "type": "RightsMetadata",
                    "rightsStatus": "notStated",
                    "sourceArtifact": "https://publisher.example/source/other.json",
                    "sourceDigest": "sha256:" + "0" * 64,
                },
            ),
        )


def test_preserves_an_explicit_publisher_concept_iri() -> None:
    publisher_iri = "https://publisher.example/concepts/official-42"
    payload = b'{"terms":[{"id":"https://publisher.example/concepts/official-42","label":"Publisher identity"}]}\n'
    source_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    source = _source(
        (
            _observation(
                1,
                label="Publisher identity",
                publisher_concept_iri=publisher_iri,
                publisher_source_digest=source_digest,
            ),
        ),
        payload=payload,
    )

    release = _build(source)

    assert release.concepts[0]["id"] == publisher_iri
    assert release.concepts[0]["identityKind"] == "publisherConceptIri"
    assert release.concepts[0]["publisherIdentifier"]["sourceDigest"] == source_digest
    assert "localRecordId" not in release.concepts[0]


def test_rejects_an_unqualified_publisher_identity_shortcut() -> None:
    observation = _observation(
        1,
        label="Unqualified identity",
        local_record_id=_local_record_id(1),
    )
    observation["publisherConceptIri"] = "https://publisher.example/concepts/unqualified"

    with pytest.raises(
        SourceControlledResourceError,
        match="unqualified identity or governance fields",
    ):
        _source((observation,))


@pytest.mark.parametrize("field", ("authorityUri", "sourceUri"))
def test_rejects_publisher_identity_outside_its_qualified_source(field: str) -> None:
    publisher_iri = "https://publisher.example/concepts/official-42"
    payload = b'{"terms":[{"id":"https://publisher.example/concepts/official-42"}]}\n'
    source_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    observation = _observation(
        1,
        label="Publisher identity",
        publisher_concept_iri=publisher_iri,
        publisher_source_digest=source_digest,
    )
    observation["identifiers"][0][field] = "https://other.example/source"
    source = _source((observation,), payload=payload)

    with pytest.raises(SourceConceptReleaseError, match="authority|source artifact"):
        _build(source)


def test_label_rename_changes_the_release_but_not_source_scoped_identity() -> None:
    local_id = _local_record_id(7)
    first = _build(
        _source(
            (_observation(1, label="Original label", local_record_id=local_id),),
            payload=b'{"label":"Original label"}\n',
            resource_id="source-concept-label-first",
        )
    )
    renamed = _build(
        _source(
            (_observation(1, label="Renamed label", local_record_id=local_id),),
            payload=b'{"label":"Renamed label"}\n',
            resource_id="source-concept-label-renamed",
        )
    )

    assert first.concepts[0]["id"] == renamed.concepts[0]["id"]
    assert first.release_id != renamed.release_id
    assert (
        first.release_manifest["sourceCapture"]["logicalDigest"]
        != renamed.release_manifest["sourceCapture"]["logicalDigest"]
    )


def test_equal_labels_never_collapse_distinct_local_records() -> None:
    source = _source(
        (
            _observation(1, label="Duplicate", local_record_id=_local_record_id(1)),
            _observation(2, label="Duplicate", local_record_id=_local_record_id(2)),
        )
    )

    release = _build(source)

    assert len(release.concepts) == 2
    assert len({row["id"] for row in release.concepts}) == 2


def test_identity_requires_explicit_publisher_iri_or_uuid7_local_record() -> None:
    source = _source((_observation(1, label="No identity input"),))

    with pytest.raises(SourceConceptReleaseError, match="localRecordId"):
        _build(source)


def test_refuses_two_observations_claiming_one_publisher_concept() -> None:
    shared = "https://publisher.example/concepts/shared"
    payload = b'{"terms":[{"id":"https://publisher.example/concepts/shared"}]}\n'
    source_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    source = _source(
        (
            _observation(
                1,
                label="First",
                publisher_concept_iri=shared,
                publisher_source_digest=source_digest,
            ),
            _observation(
                2,
                label="Second",
                publisher_concept_iri=shared,
                publisher_source_digest=source_digest,
            ),
        ),
        payload=payload,
    )

    with pytest.raises(SourceConceptReleaseError, match="repeats a concept id"):
        _build(source)


def test_build_is_order_independent_and_content_derived() -> None:
    source = _source(
        (
            _observation(1, label="First", local_record_id=_local_record_id(1)),
            _observation(2, label="Second", local_record_id=_local_record_id(2)),
        )
    )
    identifiers = tuple(str(row["id"]) for row in source.observations)

    forward = _build(source, selected=identifiers)
    reverse = _build(source, selected=tuple(reversed(identifiers)))

    assert forward.release_id == reverse.release_id
    assert forward.logical_digest == reverse.logical_digest
    assert forward.artifact_bytes() == reverse.artifact_bytes()


def test_source_release_supersession_is_distinct_content_addressed_and_reproducible(
    tmp_path: Path,
) -> None:
    first = _build(
        _source(
            (
                _observation(
                    1,
                    label="First publisher release",
                    local_record_id=_local_record_id(1),
                ),
            ),
            payload=b'{"release":"first"}\n',
            resource_id="source-release-first",
        )
    )
    second = _build(
        _source(
            (
                _observation(
                    1,
                    label="Second publisher release",
                    local_record_id=_local_record_id(1),
                ),
            ),
            payload=b'{"release":"second"}\n',
            resource_id="source-release-second",
        ),
        supersedes=(first,),
    )
    prior_root = first.write_to(tmp_path / "superseded-release")
    prior_view = SourceConceptReleaseView.open(
        prior_root,
        expected_manifest_digest=first.manifest_digest,
    )
    reproduced = build_source_concept_release_bundle(
        second.source_bundle,
        semantic_ring="subject",
        selected_observation_ids=tuple(
            str(row["id"]) for row in second.source_bundle.observations
        ),
        selection_policy=SELECTION_POLICY,
        rights_metadata=second.rights_metadata,
        supersedes=(prior_view,),
    )

    assert "sourceReleaseSupersessions" not in first.release_manifest
    assert first.release_manifest["schemaVersion"] == "1.0"
    assert (
        second.release_manifest["schemaVersion"]
        == SOURCE_CONCEPT_RELEASE_LINEAGE_VERSION
    )
    assert second.artifact_bytes() == reproduced.artifact_bytes()
    assert second.release_id == reproduced.release_id
    assert second.lifecycle_records == ()
    relation = second.source_release_supersessions[0]
    assert relation["type"] == SOURCE_RELEASE_SUPERSESSION_TYPE
    assert relation["schemaVersion"] == SOURCE_RELEASE_SUPERSESSION_VERSION
    assert relation["id"] == (
        "urn:ref:source-release-supersession:"
        + str(relation["contentDigest"]).removeprefix("sha256:")
    )
    assert relation["supersededRelease"] == {
        "releaseId": first.release_id,
        "semanticRing": first.semantic_ring,
        "sourceScheme": SCHEME_ID,
        "manifestDigest": first.manifest_digest,
        "releaseDigest": first.release_digest,
        "logicalDigest": first.logical_digest,
    }
    root = second.write_to(tmp_path / "superseding-release")
    reopened = SourceConceptReleaseView.open(
        root,
        expected_manifest_digest=second.manifest_digest,
    )
    assert reopened.source_release_supersessions == second.source_release_supersessions

    forged_prior_view = SourceConceptReleaseView(
        path=prior_root,
        bundle=first,
        manifest_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(SourceConceptReleaseError, match="manifest digest differs"):
        build_source_concept_release_bundle(
            second.source_bundle,
            semantic_ring="subject",
            selected_observation_ids=tuple(
                str(row["id"]) for row in second.source_bundle.observations
            ),
            selection_policy=SELECTION_POLICY,
            rights_metadata=second.rights_metadata,
            supersedes=(forged_prior_view,),
        )


def test_source_release_supersession_identity_binds_the_complete_predecessor_set() -> None:
    predecessor_p = _build(
        _source(
            (
                _observation(
                    1,
                    label="Predecessor P",
                    local_record_id=_local_record_id(1),
                ),
            ),
            payload=b'{"release":"p"}\n',
            resource_id="source-release-predecessor-p",
        )
    )
    predecessor_q = _build(
        _source(
            (
                _observation(
                    1,
                    label="Predecessor Q",
                    local_record_id=_local_record_id(1),
                ),
            ),
            payload=b'{"release":"q"}\n',
            resource_id="source-release-predecessor-q",
        )
    )
    successor_source = _source(
        (
            _observation(
                1,
                label="Re-cut successor",
                local_record_id=_local_record_id(1),
            ),
        ),
        payload=b'{"release":"successor"}\n',
        resource_id="source-release-successor-recut",
    )

    p_only = _build(successor_source, supersedes=(predecessor_p,))
    p_and_q = _build(
        successor_source,
        supersedes=(predecessor_p, predecessor_q),
    )
    q_and_p = _build(
        successor_source,
        supersedes=(predecessor_q, predecessor_p),
    )
    p_only_relation = p_only.source_release_supersessions[0]
    p_and_q_relation = next(
        relation
        for relation in p_and_q.source_release_supersessions
        if relation["supersededRelease"]["releaseId"]
        == predecessor_p.release_id
    )

    assert p_only_relation["successorBasisDigest"] == (
        p_and_q_relation["successorBasisDigest"]
    )
    assert p_only_relation["successorLineageDigest"] != (
        p_and_q_relation["successorLineageDigest"]
    )
    assert p_only_relation["id"] != p_and_q_relation["id"]
    assert p_only.release_id != p_and_q.release_id
    assert p_and_q.artifact_bytes() == q_and_p.artifact_bytes()
    assert {
        relation["successorLineageDigest"]
        for relation in p_and_q.source_release_supersessions
    } == {p_and_q_relation["successorLineageDigest"]}


def test_source_release_supersession_rejects_cross_ring_and_resealed_tampering() -> None:
    prior = _build(
        _source(
            (
                _observation(
                    1,
                    label="Prior release",
                    local_record_id=_local_record_id(1),
                ),
            ),
            resource_id="source-release-prior",
        )
    )
    current_source = _source(
        (
            _observation(
                1,
                label="Current release",
                local_record_id=_local_record_id(1),
            ),
        ),
        payload=b'{"release":"current"}\n',
        resource_id="source-release-current",
    )
    with pytest.raises(SourceConceptReleaseError, match="same semantic ring"):
        _build(
            current_source,
            ring="entity",
            supersedes=(prior,),
        )

    current = _build(current_source, supersedes=(prior,))
    tampered_manifest = json.loads(
        current.artifact_bytes()["release-manifest.json"]
    )
    relation = tampered_manifest["sourceReleaseSupersessions"][0]
    relation["successorBasisDigest"] = "sha256:" + "0" * 64
    relation_basis = {
        key: value
        for key, value in relation.items()
        if key not in {"id", "contentDigest"}
    }
    relation_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            relation_basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    ).hexdigest()
    relation["contentDigest"] = relation_digest
    relation["id"] = (
        "urn:ref:source-release-supersession:"
        + relation_digest.removeprefix("sha256:")
    )
    manifest_basis = {
        key: value
        for key, value in tampered_manifest.items()
        if key not in {"id", "releaseDigest"}
    }
    release_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            manifest_basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    ).hexdigest()
    tampered_manifest["releaseDigest"] = release_digest
    tampered_manifest["id"] = (
        "urn:ref:source-concept-release:subject:"
        + release_digest.removeprefix("sha256:")
    )
    with pytest.raises(
        SourceConceptReleaseError,
        match="successor release basis|stale or differs",
    ):
        SourceConceptReleaseBundle(
            release_manifest=tampered_manifest,
            concepts=current.concepts,
            lifecycle_records=current.lifecycle_records,
            source_bundle=current.source_bundle,
            rights_metadata=current.rights_metadata,
        )


def test_lifecycle_events_are_typed_reviewed_and_ring_scoped() -> None:
    observation = _observation(
        1,
        label="Renamed label",
        local_record_id=_local_record_id(1),
    )
    source = _source((observation,))
    concept_id = source_scoped_concept_iri(SCHEME_ID, _local_record_id(1))
    event = {
        "id": "urn:ref:test:lifecycle:rename-1",
        "eventType": "rename",
        "semanticRing": "subject",
        "effectiveAt": "2026-08-04T12:00:00Z",
        "priorConcepts": [concept_id],
        "resultingConcepts": [concept_id],
        "evidence": ["urn:ref:test:evidence:rename-1"],
        "reviewedBy": "https://refspec.org/reviewers/example",
        "reviewedAt": "2026-08-04T13:00:00Z",
    }

    release = _build(source, lifecycle=(event,))

    assert json.loads(release.artifact_bytes()["lifecycle.jsonl"].splitlines()[0]) == event
    assert release.release_manifest["lifecycleRecordCount"] == 1


def test_lifecycle_events_reject_invalid_cardinality_and_governance() -> None:
    source = _source(
        (
            _observation(
                1,
                label="Changed",
                local_record_id=_local_record_id(1),
            ),
        )
    )
    concept_id = source_scoped_concept_iri(SCHEME_ID, _local_record_id(1))
    event = {
        "id": "urn:ref:test:lifecycle:split-1",
        "eventType": "split",
        "semanticRing": "subject",
        "effectiveAt": "2026-08-04T12:00:00Z",
        "priorConcepts": [concept_id],
        "resultingConcepts": [concept_id],
        "evidence": ["urn:ref:test:evidence:split-1"],
        "reviewedBy": "https://refspec.org/reviewers/example",
        "reviewedAt": "2026-08-04T13:00:00Z",
    }

    with pytest.raises(SourceConceptReleaseError, match="cardinality"):
        _build(source, lifecycle=(event,))
    with pytest.raises(SourceConceptReleaseError, match="admission or permission"):
        _build(source, lifecycle=({**event, "emissionAuthorized": True},))


def test_reconciliation_is_exactly_sealed_and_pending_review_is_refused() -> None:
    source = _source((_observation(1, label="Reviewed", local_record_id=_local_record_id(1)),))
    resolved = {
        "currentManifestId": source.resource_manifest["id"],
        "requiresHumanReview": False,
        "previousManifestId": None,
        "review": None,
    }
    release = _build(source, reconciliation=resolved)

    assert json.loads(release.artifact_bytes()["reconciliation.json"].decode("utf-8")) == resolved
    assert release.release_manifest["sourceCapture"]["reconciliationDigest"].startswith("sha256:")

    with pytest.raises(SourceConceptReleaseError, match="resolve human identity review"):
        _build(
            source,
            reconciliation={
                **resolved,
                "requiresHumanReview": True,
            },
        )


def test_open_verifies_external_pin_complete_files_and_nested_source(
    tmp_path: Path,
) -> None:
    source = _source((_observation(1, label="Pinned", local_record_id=_local_record_id(1)),))
    release = _build(source)
    root = release.write_to(tmp_path / "release")
    manifest = root / "bundle-manifest.json"

    reopened = SourceConceptReleaseView.open(
        manifest,
        expected_manifest_digest=release.manifest_digest,
    )
    assert reopened.release_id == release.release_id
    assert reopened.logical_digest == release.logical_digest
    assert reopened.bundle.artifact_bytes() == release.artifact_bytes()
    with pytest.raises(TypeError):
        reopened.source_bundle.observations[0]["labels"][0]["value"] = "Changed"  # type: ignore[index]

    concepts_path = root / "concepts.jsonl"
    concepts_path.write_bytes(concepts_path.read_bytes() + b"{}\n")
    with pytest.raises(SourceConceptReleaseError, match="bytes differ"):
        SourceConceptReleaseView.open(
            manifest,
            expected_manifest_digest=release.manifest_digest,
        )


def test_external_manifest_pin_refuses_a_resealed_forgery(tmp_path: Path) -> None:
    release = _build(_source((_observation(1, label="Pinned", local_record_id=_local_record_id(1)),)))
    root = release.write_to(tmp_path / "release")
    manifest_path = root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["logicalDigest"] = "sha256:" + "0" * 64
    from refspec.storage import canonical_json

    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(SourceConceptReleaseError, match="manifest digest differs"):
        SourceConceptReleaseView.open(
            manifest_path,
            expected_manifest_digest=release.manifest_digest,
        )


def test_atlas_authority_rejects_a_publicly_constructed_source_release_view(
    tmp_path: Path,
) -> None:
    release = _build(
        _source(
            (
                _observation(
                    1,
                    label="Pinned",
                    local_record_id=_local_record_id(1),
                ),
            )
        )
    )
    forged = SourceConceptReleaseView(
        path=tmp_path,
        bundle=release,
        manifest_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(ConceptReleaseError, match="exact supported release"):
        concept_release_pin(forged)  # type: ignore[arg-type]


def test_concept_release_pin_reports_a_domain_error_for_a_non_string_ring() -> None:
    release = _build(
        _source(
            (
                _observation(
                    1,
                    label="Pinned",
                    local_record_id=_local_record_id(1),
                ),
            )
        )
    )
    pin = concept_release_pin(release)
    pin["semanticRing"] = []

    with pytest.raises(ConceptReleaseError, match="must be subject, entity, value"):
        normalize_concept_release_pin(pin)
